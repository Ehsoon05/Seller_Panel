from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Seller, SellerLedger, SellerOffer, SellerService
from .schemas import CreateServiceBody, LoginBody, ServiceUpdateBody
from .security import (
    COOKIE_NAME,
    current_seller,
    get_session,
    issue_seller_token,
    set_session_cookie,
    verify_password,
)
from .service import (
    create_service,
    dashboard,
    offer_out,
    refresh_service,
    remove_service,
    seller_out,
    service_out,
    toggle_service,
    update_service,
)

router = APIRouter(prefix="/api")


@router.post("/auth/login")
async def login(body: LoginBody, response: Response, session: AsyncSession = Depends(get_session)):
    seller = (
        await session.execute(
            select(Seller).where(Seller.username == body.username.strip().casefold())
        )
    ).scalar_one_or_none()
    if seller is None or not seller.is_active or not verify_password(body.password, seller.password_hash):
        raise HTTPException(status_code=401, detail="نام کاربری یا رمز عبور صحیح نیست.")
    set_session_cookie(response, issue_seller_token(seller.id))
    return seller_out(seller)


@router.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
async def me(seller: Seller = Depends(current_seller)):
    return seller_out(seller)


@router.get("/dashboard")
async def get_dashboard(
    seller: Seller = Depends(current_seller),
    session: AsyncSession = Depends(get_session),
):
    return {**await dashboard(session, seller.id), "wallet_balance": seller.wallet_balance}


@router.get("/offers")
async def offers(
    seller: Seller = Depends(current_seller),
    session: AsyncSession = Depends(get_session),
):
    values = (
        await session.execute(
            select(SellerOffer)
            .where(SellerOffer.seller_id == seller.id, SellerOffer.is_active.is_(True))
            .order_by(SellerOffer.title)
        )
    ).scalars().all()
    return [offer_out(item) for item in values]


@router.get("/services")
async def services(
    q: str | None = Query(default=None, max_length=180),
    status: str | None = None,
    seller: Seller = Depends(current_seller),
    session: AsyncSession = Depends(get_session),
):
    query = select(SellerService).where(SellerService.seller_id == seller.id)
    if status:
        query = query.where(SellerService.status == status)
    if q and q.strip():
        value = f"%{q.strip()}%"
        query = query.where(
            or_(
                SellerService.panel_username.ilike(value),
                SellerService.display_name.ilike(value),
                SellerService.public_url.ilike(value),
                SellerService.upstream_url.ilike(value),
            )
        )
    values = (
        await session.execute(query.order_by(SellerService.created_at.desc()).limit(500))
    ).scalars().all()
    return [service_out(item) for item in values]


@router.post("/services")
async def provision(
    body: CreateServiceBody,
    seller: Seller = Depends(current_seller),
    session: AsyncSession = Depends(get_session),
):
    try:
        value = await create_service(session, seller, body)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc) or "ساخت سرویس انجام نشد.") from exc
    return service_out(value)


async def _owned_service(
    service_id: int,
    seller: Seller,
    session: AsyncSession,
) -> SellerService:
    service = (
        await session.execute(
            select(SellerService).where(
                SellerService.id == service_id,
                SellerService.seller_id == seller.id,
            )
        )
    ).scalar_one_or_none()
    if service is None:
        raise HTTPException(status_code=404, detail="سرویس پیدا نشد.")
    return service


@router.post("/services/{service_id}/refresh")
async def refresh(
    service_id: int,
    seller: Seller = Depends(current_seller),
    session: AsyncSession = Depends(get_session),
):
    service = await _owned_service(service_id, seller, session)
    try:
        return service_out(await refresh_service(session, service))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc) or "به‌روزرسانی انجام نشد.") from exc


@router.post("/services/{service_id}/status")
async def set_status(
    service_id: int,
    enabled: bool,
    seller: Seller = Depends(current_seller),
    session: AsyncSession = Depends(get_session),
):
    service = await _owned_service(service_id, seller, session)
    try:
        return service_out(await toggle_service(session, service, enabled))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc) or "تغییر وضعیت انجام نشد.") from exc


@router.patch("/services/{service_id}")
async def edit_service(
    service_id: int,
    body: ServiceUpdateBody,
    seller: Seller = Depends(current_seller),
    session: AsyncSession = Depends(get_session),
):
    service = await _owned_service(service_id, seller, session)
    try:
        return service_out(await update_service(session, service, body))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc) or "ویرایش سرویس انجام نشد.") from exc


@router.delete("/services/{service_id}")
async def remove_owned_service(
    service_id: int,
    seller: Seller = Depends(current_seller),
    session: AsyncSession = Depends(get_session),
):
    service = await _owned_service(service_id, seller, session)
    try:
        await remove_service(session, service)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc) or "حذف سرویس انجام نشد.") from exc
    return {"deleted": True}


@router.get("/ledger")
async def ledger(
    seller: Seller = Depends(current_seller),
    session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.execute(
            select(SellerLedger)
            .where(SellerLedger.seller_id == seller.id)
            .order_by(SellerLedger.created_at.desc())
            .limit(200)
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
