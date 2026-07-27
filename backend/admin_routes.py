from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Seller, SellerLedger, SellerOffer, SellerService
from .panels import PanelError, list_panels
from .schemas import BalanceBody, OfferBody, SellerCreateBody, SellerUpdateBody
from .security import current_admin, get_session, hash_password
from .service import offer_out, remove_service, seller_out, service_out

router = APIRouter(prefix="/api/admin", dependencies=[Depends(current_admin)])


@router.get("/summary")
async def summary(session: AsyncSession = Depends(get_session)):
    sellers = await session.scalar(select(func.count(Seller.id)))
    active_sellers = await session.scalar(
        select(func.count(Seller.id)).where(Seller.is_active.is_(True))
    )
    services = await session.scalar(select(func.count(SellerService.id)))
    revenue = await session.scalar(
        select(func.coalesce(func.sum(-SellerLedger.amount), 0)).where(
            SellerLedger.kind == "purchase"
        )
    )
    return {
        "sellers": int(sellers or 0),
        "active_sellers": int(active_sellers or 0),
        "services": int(services or 0),
        "revenue": int(revenue or 0),
    }


@router.get("/panels")
async def panels():
    try:
        return [
            {
                "key": panel.key,
                "title": panel.title,
                "panel_type": panel.panel_type,
                "hwid_limit": panel.hwid_limit,
            }
            for panel in list_panels()
        ]
    except PanelError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/sellers")
async def sellers(
    q: str | None = Query(default=None, max_length=120),
    session: AsyncSession = Depends(get_session),
):
    query = select(Seller)
    if q and q.strip():
        value = f"%{q.strip()}%"
        query = query.where(
            or_(Seller.username.ilike(value), Seller.display_name.ilike(value))
        )
    rows = (await session.execute(query.order_by(Seller.created_at.desc()))).scalars().all()
    counts = dict(
        (
            await session.execute(
                select(SellerService.seller_id, func.count(SellerService.id)).group_by(
                    SellerService.seller_id
                )
            )
        ).all()
    )
    return [{**seller_out(row), "service_count": int(counts.get(row.id, 0))} for row in rows]


@router.post("/sellers")
async def create_seller(body: SellerCreateBody, session: AsyncSession = Depends(get_session)):
    username = body.username.strip().casefold()
    exists = await session.scalar(select(Seller.id).where(Seller.username == username))
    if exists:
        raise HTTPException(status_code=409, detail="این نام کاربری قبلاً ثبت شده است.")
    seller = Seller(
        username=username,
        display_name=body.display_name.strip(),
        password_hash=hash_password(body.password),
        wallet_balance=body.initial_balance,
        allow_negative_balance=body.allow_negative_balance,
        is_active=body.is_active,
    )
    if body.initial_balance < 0 and not body.allow_negative_balance:
        raise HTTPException(
            status_code=400,
            detail="برای موجودی اولیه منفی باید مجوز بدهکاری این همکار فعال باشد.",
        )
    session.add(seller)
    await session.flush()
    if body.initial_balance:
        session.add(
            SellerLedger(
                seller_id=seller.id,
                amount=body.initial_balance,
                balance_after=body.initial_balance,
                kind="credit",
                description="موجودی اولیه",
            )
        )
    await session.commit()
    await session.refresh(seller)
    return seller_out(seller)


@router.patch("/sellers/{seller_id}")
async def update_seller(
    seller_id: int,
    body: SellerUpdateBody,
    session: AsyncSession = Depends(get_session),
):
    seller = await session.get(Seller, seller_id)
    if seller is None:
        raise HTTPException(status_code=404, detail="همکار پیدا نشد.")
    if body.display_name is not None:
        seller.display_name = body.display_name.strip()
    if body.password is not None:
        seller.password_hash = hash_password(body.password)
    if body.allow_negative_balance is not None:
        if not body.allow_negative_balance and seller.wallet_balance < 0:
            raise HTTPException(
                status_code=409,
                detail="ابتدا بدهی همکار را تسویه کنید، سپس مجوز بدهکاری را ببندید.",
            )
        seller.allow_negative_balance = body.allow_negative_balance
    if body.is_active is not None:
        seller.is_active = body.is_active
    seller.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(seller)
    return seller_out(seller)


@router.post("/sellers/{seller_id}/balance")
async def adjust_balance(
    seller_id: int,
    body: BalanceBody,
    session: AsyncSession = Depends(get_session),
):
    seller = await session.get(Seller, seller_id)
    if seller is None:
        raise HTTPException(status_code=404, detail="همکار پیدا نشد.")
    new_balance = seller.wallet_balance + body.amount
    if new_balance < 0 and not seller.allow_negative_balance:
        raise HTTPException(status_code=409, detail="موجودی نمی‌تواند منفی شود.")
    seller.wallet_balance = new_balance
    seller.updated_at = datetime.now(timezone.utc)
    session.add(
        SellerLedger(
            seller_id=seller.id,
            amount=body.amount,
            balance_after=new_balance,
            kind="credit" if body.amount >= 0 else "debit",
            description=body.description.strip(),
        )
    )
    await session.commit()
    return seller_out(seller)


@router.get("/sellers/{seller_id}/offers")
async def offers(seller_id: int, session: AsyncSession = Depends(get_session)):
    rows = (
        await session.execute(
            select(SellerOffer)
            .where(SellerOffer.seller_id == seller_id)
            .order_by(SellerOffer.created_at.desc())
        )
    ).scalars().all()
    return [offer_out(row) for row in rows]


def _apply_offer(offer: SellerOffer, body: OfferBody) -> None:
    offer.title = body.title.strip()
    offer.panel_key = body.panel_key.strip()
    offer.price_toman = body.price_toman
    offer.volume_gb = body.volume_gb
    offer.lock_volume = body.lock_volume
    offer.default_duration_days = body.default_duration_days
    offer.allowed_time_modes_json = json.dumps(body.allowed_time_modes, separators=(",", ":"))
    offer.default_time_mode = (
        body.default_time_mode
        if body.default_time_mode in body.allowed_time_modes
        else body.allowed_time_modes[0]
    )
    offer.lock_time = body.lock_time
    offer.name_prefix = body.name_prefix.strip()
    offer.panel_hwid_limit = body.panel_hwid_limit
    offer.subscription_device_limit = body.subscription_device_limit
    offer.profile_title = (body.profile_title or "").strip() or None
    offer.support_url = (body.support_url or "").strip() or None
    offer.show_header = body.show_header
    offer.show_config_preview = body.show_config_preview
    offer.info_proxies_enabled = body.info_proxies_enabled
    offer.is_active = body.is_active
    offer.updated_at = datetime.now(timezone.utc)


@router.post("/sellers/{seller_id}/offers")
async def create_offer(
    seller_id: int,
    body: OfferBody,
    session: AsyncSession = Depends(get_session),
):
    if await session.get(Seller, seller_id) is None:
        raise HTTPException(status_code=404, detail="همکار پیدا نشد.")
    if body.panel_key not in {panel.key for panel in list_panels()}:
        raise HTTPException(status_code=400, detail="پنل ساخت معتبر نیست.")
    offer = SellerOffer(seller_id=seller_id)
    _apply_offer(offer, body)
    session.add(offer)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=409, detail="سرویسی با این عنوان برای همکار وجود دارد.")
    await session.refresh(offer)
    return offer_out(offer)


@router.put("/offers/{offer_id}")
async def update_offer(
    offer_id: int,
    body: OfferBody,
    session: AsyncSession = Depends(get_session),
):
    offer = await session.get(SellerOffer, offer_id)
    if offer is None:
        raise HTTPException(status_code=404, detail="سرویس همکاری پیدا نشد.")
    if body.panel_key not in {panel.key for panel in list_panels()}:
        raise HTTPException(status_code=400, detail="پنل ساخت معتبر نیست.")
    old_prefix = offer.name_prefix
    _apply_offer(offer, body)
    if old_prefix != offer.name_prefix:
        match = __import__("re").search(r"(\d+)$", offer.name_prefix)
        offer.next_sequence = int(match.group(1)) if match else 1
    await session.commit()
    await session.refresh(offer)
    return offer_out(offer)


@router.delete("/offers/{offer_id}")
async def delete_offer(offer_id: int, session: AsyncSession = Depends(get_session)):
    offer = await session.get(SellerOffer, offer_id)
    if offer is None:
        raise HTTPException(status_code=404, detail="سرویس همکاری پیدا نشد.")
    used = await session.scalar(
        select(func.count(SellerService.id)).where(SellerService.offer_id == offer.id)
    )
    if used:
        offer.is_active = False
    else:
        await session.delete(offer)
    await session.commit()
    return {"deleted": not bool(used), "deactivated": bool(used)}


@router.get("/services")
async def services(
    q: str | None = Query(default=None, max_length=180),
    seller_id: int | None = None,
    session: AsyncSession = Depends(get_session),
):
    query = select(SellerService)
    if seller_id:
        query = query.where(SellerService.seller_id == seller_id)
    if q and q.strip():
        value = f"%{q.strip()}%"
        query = query.where(
            or_(
                SellerService.panel_username.ilike(value),
                SellerService.display_name.ilike(value),
                SellerService.public_url.ilike(value),
            )
        )
    rows = (
        await session.execute(query.order_by(SellerService.created_at.desc()).limit(500))
    ).scalars().all()
    return [service_out(row) for row in rows]


@router.delete("/services/{service_id}")
async def delete_service_as_admin(
    service_id: int,
    session: AsyncSession = Depends(get_session),
):
    service = await session.get(SellerService, service_id)
    if service is None:
        raise HTTPException(status_code=404, detail="یوزر ساخته‌شده پیدا نشد.")
    try:
        await remove_service(session, service)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc) or "حذف یوزر انجام نشد.") from exc
    return {"deleted": True}


@router.get("/sellers/{seller_id}/ledger")
async def ledger(seller_id: int, session: AsyncSession = Depends(get_session)):
    rows = (
        await session.execute(
            select(SellerLedger)
            .where(SellerLedger.seller_id == seller_id)
            .order_by(SellerLedger.created_at.desc())
            .limit(300)
        )
    ).scalars().all()
    return [
        {
            "id": row.id,
            "amount": row.amount,
            "balance_after": row.balance_after,
            "kind": row.kind,
            "description": row.description,
            "service_id": row.service_id,
            "created_at": row.created_at,
        }
        for row in rows
    ]
