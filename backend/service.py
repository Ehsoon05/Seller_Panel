from __future__ import annotations

import asyncio
import html
import json
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx
from fastapi import HTTPException
from sqlalchemy import case, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import Seller, SellerLedger, SellerOffer, SellerService
from .panels import (
    PanelError,
    create_user,
    delete_user,
    fetch_user,
    get_panel,
    set_user_status,
    update_user,
)
from .schemas import CreateServiceBody, ServiceUpdateBody


logger = logging.getLogger(__name__)


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
        "allow_negative_balance": seller.allow_negative_balance,
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


async def delete_subscription(service: SellerService) -> None:
    if not settings.subscription_sync_url or not settings.subscription_sync_token:
        return
    url = f"{settings.subscription_sync_url.rstrip('/')}/{quote(service.public_token, safe='')}"
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.delete(
            url,
            headers={"Authorization": f"Bearer {settings.subscription_sync_token}"},
        )
    if response.status_code not in {200, 204, 404}:
        response.raise_for_status()


async def notify_service_created(
    seller: Seller,
    offer: SellerOffer,
    service: SellerService,
) -> None:
    if not settings.notification_bot_token or not settings.notification_recipients:
        return
    duration = (
        "نامحدود"
        if service.duration_days == 0
        else f"{service.duration_days:,} روز"
    )
    volume = "نامحدود" if service.volume_gb == 0 else f"{service.volume_gb:,} گیگ"
    mode = {
        "date": "Active - تاریخ‌دار",
        "on_hold": "On Hold - شروع با اولین اتصال",
        "unlimited": "Active - بدون محدودیت زمانی",
    }.get(service.time_mode, service.time_mode)
    text = (
        "<b>ساخت موفق سرویس همکاری</b>\n\n"
        f"همکار: {html.escape(seller.display_name)} (@{html.escape(seller.username)})\n"
        f"سرویس: {html.escape(offer.title)}\n"
        f"یوزرنیم کانفیگ: <code>{html.escape(service.panel_username)}</code>\n"
        f"پنل سازنده: <code>{html.escape(service.panel_key)}</code>\n"
        f"حجم: {volume}\n"
        f"مدت: {duration}\n"
        f"نوع ساخت: {html.escape(mode)}\n"
        f"مبلغ: {service.price_toman:,} تومان\n"
        f"موجودی همکار: {seller.wallet_balance:,} تومان"
    )
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            for chat_id in settings.notification_recipients:
                response = await client.post(
                    f"https://api.telegram.org/bot{settings.notification_bot_token}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                )
                response.raise_for_status()
    except Exception:
        logger.exception("Could not send seller service notification")


async def create_service(
    session: AsyncSession,
    seller: Seller,
    body: CreateServiceBody,
) -> SellerService:
    seller_id = seller.id
    existing = (
        await session.execute(
            select(SellerService).where(
                SellerService.seller_id == seller_id,
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
                SellerOffer.seller_id == seller_id,
                SellerOffer.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if offer is None:
        raise HTTPException(status_code=404, detail="سرویس انتخاب‌شده در دسترس نیست.")
    offer_price = int(offer.price_toman)

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

    panel = get_panel(offer.panel_key)
    requested_username = (body.panel_username or "").strip()
    username = requested_username or _username_for_offer(offer)
    if requested_username:
        current = await fetch_user(panel, username)
        if str(current.get("status") or "") != "deleted":
            raise HTTPException(
                status_code=409,
                detail=(
                    f"یوزرنیم «{username}» از قبل در پنل {panel.title} وجود دارد. "
                    "یک یوزرنیم دیگر وارد کنید."
                ),
            )

    balance_condition = (
        Seller.id == seller_id
        if seller.allow_negative_balance
        else (Seller.id == seller_id) & (Seller.wallet_balance >= offer_price)
    )
    charged = (
        await session.execute(
            update(Seller)
            .where(balance_condition)
            .values(
                wallet_balance=Seller.wallet_balance - offer_price,
                updated_at=datetime.now(timezone.utc),
            )
        )
    ).rowcount
    if not charged:
        raise HTTPException(status_code=409, detail="موجودی پنل برای ساخت این سرویس کافی نیست.")
    await session.flush()
    balance = await session.scalar(select(Seller.wallet_balance).where(Seller.id == seller_id))
    purchase_ledger = SellerLedger(
        seller_id=seller_id,
        amount=-offer_price,
        balance_after=int(balance or 0),
        kind="purchase",
        description=f"رزرو ساخت {offer.title} برای {username}",
    )
    session.add(purchase_ledger)
    await session.commit()
    charge_ledger_id = purchase_ledger.id
    await session.refresh(offer)

    try:
        payload = await create_user(
            panel,
            username=username,
            volume_gb=offer.volume_gb,
            duration_days=duration_days,
            time_mode=mode,
            hwid_limit=offer.panel_hwid_limit,
        )
    except Exception as exc:
        await _cancel_charge(
            session,
            seller_id,
            offer_price,
            charge_ledger_id,
        )
        detail = str(exc) or "پنل سازنده ساخت سرویس را نپذیرفت."
        lowered = detail.casefold()
        if any(value in lowered for value in ("already exist", "duplicate", "exists")):
            raise HTTPException(
                status_code=409,
                detail=f"یوزرنیم «{username}» قبلاً در پنل سازنده ثبت شده است.",
            ) from exc
        raise

    public_token = secrets.token_urlsafe(32)
    public_url = (
        f"{settings.subscription_public_base_url.rstrip('/')}/token/"
        f"{quote(public_token, safe='')}"
    )
    service = SellerService(
        request_id=body.request_id,
        seller_id=seller_id,
        offer_id=offer.id,
        panel_key=panel.key,
        panel_username=str(payload.get("username") or username),
        display_name=username,
        upstream_url=str(payload["_subscription_url"]),
        public_token=public_token,
        public_url=public_url,
        volume_gb=offer.volume_gb,
        duration_days=duration_days,
        time_mode=mode,
        price_toman=offer_price,
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
            await _cancel_charge(
                session,
                seller_id,
                offer_price,
                charge_ledger_id,
            )
        raise
    await session.refresh(seller)
    asyncio.create_task(notify_service_created(seller, offer, service))
    return service


async def _cancel_charge(
    session: AsyncSession,
    seller_id: int,
    amount: int,
    ledger_id: int,
) -> None:
    await session.rollback()
    removed = (
        await session.execute(
            delete(SellerLedger).where(
                SellerLedger.id == ledger_id,
                SellerLedger.seller_id == seller_id,
                SellerLedger.kind == "purchase",
            )
        )
    ).rowcount
    if removed:
        await session.execute(
            update(Seller)
            .where(Seller.id == seller_id)
            .values(
                wallet_balance=Seller.wallet_balance + amount,
                updated_at=datetime.now(timezone.utc),
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


async def update_service(
    session: AsyncSession,
    service: SellerService,
    body: ServiceUpdateBody,
) -> SellerService:
    offer = await session.get(SellerOffer, service.offer_id)
    if offer is None:
        raise HTTPException(status_code=409, detail="پلن سازنده این سرویس پیدا نشد.")
    if body.time_mode not in allowed_time_modes(offer):
        raise HTTPException(status_code=400, detail="نوع زمان برای این سرویس مجاز نیست.")
    if body.time_mode != "unlimited" and body.duration_days <= 0:
        raise HTTPException(status_code=400, detail="مدت سرویس باید بیشتر از صفر باشد.")
    duration_days = 0 if body.time_mode == "unlimited" else body.duration_days
    panel = get_panel(service.panel_key)
    payload = await update_user(
        panel,
        username=service.panel_username,
        volume_gb=body.volume_gb,
        duration_days=duration_days,
        time_mode=body.time_mode,
    )
    service.volume_gb = body.volume_gb
    service.duration_days = duration_days
    service.time_mode = body.time_mode
    service.status = str(
        payload.get("status")
        or ("on_hold" if body.time_mode == "on_hold" else "active")
    )
    service.data_limit_bytes = int(
        payload.get("data_limit")
        if payload.get("data_limit") is not None
        else body.volume_gb * 1024**3
    )
    service.used_bytes = int(payload.get("used_traffic") or service.used_bytes or 0)
    service.expires_at = (
        _timestamp(payload.get("expire"))
        if payload.get("expire") is not None
        else (
            None
            if duration_days == 0 or body.time_mode == "on_hold"
            else datetime.now(timezone.utc) + timedelta(days=duration_days)
        )
    )
    service.last_refreshed_at = datetime.now(timezone.utc)
    await sync_subscription(service, offer)
    await session.commit()
    await session.refresh(service)
    return service


async def remove_service(session: AsyncSession, service: SellerService) -> None:
    panel = get_panel(service.panel_key)
    await delete_user(panel, service.panel_username)
    await delete_subscription(service)
    await session.execute(
        update(SellerLedger)
        .where(SellerLedger.service_id == service.id)
        .values(service_id=None)
    )
    await session.delete(service)
    await session.commit()


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
