from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
from fastapi import HTTPException
from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import Seller, SellerLedger, SellerOffer, SellerService
from .panels import PanelError, create_user, delete_user, fetch_user, get_panel, set_user_status
from .schemas import CreateServiceBody


def allowed_time_modes(offer: SellerOffer) -> list[str]:
    try:
        values = json.loads(offer.allowed_time_modes_json or "[]")
    except ValueError:
        values = []
    return [str(value) for value in values if value in {"date", "on_hold", "unlimited"}] or ["date"]


def _username_for_offer(offer: SellerOffer) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "_", offer.name_prefix.strip())
    value = re.sub(r"_+", "_", value).strip("_-") or "PhantomSeller_1"
    match = re.fullmatch(r"^(.*?)(\d+)$", value)
    if match:
        base = match.group(1)
        start = int(match.group(2))
        sequence = max(start, int(offer.next_sequence or start))
    else:
        base = value
        sequence = max(1, int(offer.next_sequence or 1))
    offer.next_sequence = sequence + 1
    offer.updated_at = datetime.now(timezone.utc)
    return f"{base}{sequence}"


def seller_out(seller: Seller) -> dict:
    return {
        "id": seller.id,
        "username": seller.username,
        "display_name": seller.display_name,
        "wallet_balance": seller.wallet_balance,
        "is_active": seller.is_active,
        "created_at": seller.created_at,
        "updated_at": seller.updated_at,
    }


def offer_out(offer: SellerOffer) -> dict:
    return {
        "id": offer.id,
        "seller_id": offer.seller_id,
        "title": offer.title,
        "panel_key": offer.panel_key,
        "price_toman": offer.price_toman,
        "volume_gb": offer.volume_gb,
        "default_duration_days": offer.default_duration_days,
        "allowed_time_modes": allowed_time_modes(offer),
        "default_time_mode": offer.default_time_mode,
        "name_prefix": offer.name_prefix,
        "panel_hwid_limit": offer.panel_hwid_limit,
        "subscription_device_limit": offer.subscription_device_limit,
        "profile_title": offer.profile_title,
        "support_url": offer.support_url,
        "show_header": offer.show_header,
        "show_config_preview": offer.show_config_preview,
        "info_proxies_enabled": offer.info_proxies_enabled,
        "is_active": offer.is_active,
        "created_at": offer.created_at,
        "updated_at": offer.updated_at,
    }


def service_out(service: SellerService) -> dict:
    total = max(0, int(service.data_limit_bytes or 0))
    used = max(0, int(service.used_bytes or 0))
    return {
        "id": service.id,
        "offer_id": service.offer_id,
        "panel_key": service.panel_key,
        "panel_username": service.panel_username,
        "display_name": service.display_name,
        "public_url": service.public_url,
        "volume_gb": service.volume_gb,
        "duration_days": service.duration_days,
        "time_mode": service.time_mode,
        "price_toman": service.price_toman,
        "status": service.status,
        "used_bytes": used,
        "data_limit_bytes": total,
        "remaining_bytes": max(total - used, 0) if total else 0,
        "expires_at": service.expires_at,
        "online_at": service.online_at,
        "last_refreshed_at": service.last_refreshed_at,
        "created_at": service.created_at,
    }


def _timestamp(value) -> datetime | None:
    if not value:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(number, tz=timezone.utc) if number > 0 else None


async def sync_subscription(service: SellerService, offer: SellerOffer) -> None:
    if not settings.subscription_sync_url or not settings.subscription_sync_token:
        return
    payload = {
        "token": service.public_token,
        "upstream_url": service.upstream_url,
        "volume_gb": service.volume_gb,
        "category_key": "seller",
        "is_sold": True,
        "service_name": service.display_name or offer.title,
        "panel_username": service.panel_username,
        "profile_title": offer.profile_title,
        "device_limit": offer.subscription_device_limit,
        "show_config_preview": offer.show_config_preview,
        "info_proxies_enabled": offer.info_proxies_enabled,
        "show_header": offer.show_header,
        "channel_handle": offer.support_url,
    }
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            settings.subscription_sync_url,
            json=payload,
            headers={"Authorization": f"Bearer {settings.subscription_sync_token}"},
        )
        response.raise_for_status()


async def create_service(
    session: AsyncSession,
    seller: Seller,
    body: CreateServiceBody,
) -> SellerService:
    existing = (
        await session.execute(
            select(SellerService).where(
                SellerService.seller_id == seller.id,
                SellerService.request_id == body.request_id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return existing

    offer = (
        await session.execute(
            select(SellerOffer).where(
                SellerOffer.id == body.offer_id,
                SellerOffer.seller_id == seller.id,
                SellerOffer.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if offer is None:
        raise HTTPException(status_code=404, detail="سرویس انتخاب‌شده در دسترس نیست.")

    modes = allowed_time_modes(offer)
    mode = body.time_mode or offer.default_time_mode
    if mode not in modes:
        raise HTTPException(status_code=400, detail="نوع زمان برای این سرویس مجاز نیست.")
    duration_days = (
        int(body.duration_days)
        if body.duration_days is not None
        else int(offer.default_duration_days)
    )
    if mode == "unlimited":
        duration_days = 0
    elif duration_days <= 0:
        raise HTTPException(status_code=400, detail="مدت سرویس باید بیشتر از صفر باشد.")

    charged = (
        await session.execute(
            update(Seller)
            .where(Seller.id == seller.id, Seller.wallet_balance >= offer.price_toman)
            .values(
                wallet_balance=Seller.wallet_balance - offer.price_toman,
                updated_at=datetime.now(timezone.utc),
            )
        )
    ).rowcount
    if not charged:
        raise HTTPException(status_code=409, detail="موجودی پنل برای ساخت این سرویس کافی نیست.")
    username = _username_for_offer(offer)
    await session.flush()
    balance = await session.scalar(select(Seller.wallet_balance).where(Seller.id == seller.id))
    purchase_ledger = SellerLedger(
        seller_id=seller.id,
        amount=-offer.price_toman,
        balance_after=int(balance or 0),
        kind="purchase",
        description=f"رزرو ساخت {offer.title} برای {username}",
    )
    session.add(purchase_ledger)
    await session.commit()
    await session.refresh(offer)

    panel = get_panel(offer.panel_key)
    try:
        payload = await create_user(
            panel,
            username=username,
            volume_gb=offer.volume_gb,
            duration_days=duration_days,
            time_mode=mode,
            hwid_limit=offer.panel_hwid_limit,
        )
    except Exception:
        await _refund(session, seller.id, offer.price_toman, f"بازگشت وجه ساخت ناموفق {username}")
        raise

    public_token = secrets.token_urlsafe(32)
    public_url = (
        f"{settings.subscription_public_base_url.rstrip('/')}/token/"
        f"{quote(public_token, safe='')}"
    )
    service = SellerService(
        request_id=body.request_id,
        seller_id=seller.id,
        offer_id=offer.id,
        panel_key=panel.key,
        panel_username=str(payload.get("username") or username),
        display_name=(body.display_name or "").strip() or None,
        upstream_url=str(payload["_subscription_url"]),
        public_token=public_token,
        public_url=public_url,
        volume_gb=offer.volume_gb,
        duration_days=duration_days,
        time_mode=mode,
        price_toman=offer.price_toman,
        status=str(payload.get("status") or "active"),
        used_bytes=int(payload.get("used_traffic") or 0),
        data_limit_bytes=int(payload.get("data_limit") or 0),
        expires_at=_timestamp(payload.get("expire")),
        online_at=_timestamp(payload.get("online_at")),
        last_refreshed_at=datetime.now(timezone.utc),
    )
    session.add(service)
    try:
        await session.flush()
        purchase_ledger.service_id = service.id
        await sync_subscription(service, offer)
        await session.commit()
        await session.refresh(service)
    except Exception:
        await session.rollback()
        try:
            await delete_user(panel, username)
        finally:
            await _refund(session, seller.id, offer.price_toman, f"بازگشت وجه ثبت ناموفق {username}")
        raise
    return service


async def _refund(session: AsyncSession, seller_id: int, amount: int, description: str) -> None:
    await session.rollback()
    await session.execute(
        update(Seller)
        .where(Seller.id == seller_id)
        .values(
            wallet_balance=Seller.wallet_balance + amount,
            updated_at=datetime.now(timezone.utc),
        )
    )
    balance = await session.scalar(select(Seller.wallet_balance).where(Seller.id == seller_id))
    session.add(
        SellerLedger(
            seller_id=seller_id,
            amount=amount,
            balance_after=int(balance or 0),
            kind="refund",
            description=description,
        )
    )
    await session.commit()


async def refresh_service(session: AsyncSession, service: SellerService) -> SellerService:
    panel = get_panel(service.panel_key)
    payload = await fetch_user(panel, service.panel_username)
    service.status = str(payload.get("status") or service.status)
    service.used_bytes = int(payload.get("used_traffic") or 0)
    service.data_limit_bytes = int(payload.get("data_limit") or service.data_limit_bytes or 0)
    service.expires_at = _timestamp(payload.get("expire"))
    service.online_at = _timestamp(payload.get("online_at"))
    service.last_refreshed_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(service)
    return service


async def toggle_service(
    session: AsyncSession,
    service: SellerService,
    enabled: bool,
) -> SellerService:
    panel = get_panel(service.panel_key)
    service.status = await set_user_status(panel, service.panel_username, enabled)
    service.last_refreshed_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(service)
    return service


async def dashboard(session: AsyncSession, seller_id: int) -> dict:
    total, active, used = (
        await session.execute(
            select(
                func.count(SellerService.id),
                func.sum(case((SellerService.status.in_(["active", "on_hold"]), 1), else_=0)),
                func.coalesce(func.sum(SellerService.used_bytes), 0),
            ).where(SellerService.seller_id == seller_id)
        )
    ).one()
    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    monthly_spend = await session.scalar(
        select(func.coalesce(func.sum(-SellerLedger.amount), 0)).where(
            SellerLedger.seller_id == seller_id,
            SellerLedger.kind == "purchase",
            SellerLedger.created_at >= month_start,
        )
    )
    return {
        "total_services": int(total or 0),
        "active_services": int(active or 0),
        "used_bytes": int(used or 0),
        "monthly_spend": int(monthly_spend or 0),
    }
