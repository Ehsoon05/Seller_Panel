from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Cookie, Depends, Header, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import async_session
from .models import Seller

COOKIE_NAME = "seller_session"


async def get_session():
    async with async_session() as session:
        yield session


def hash_password(password: str) -> str:
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return bcrypt.hashpw(digest, bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        digest = hashlib.sha256(password.encode("utf-8")).digest()
        return bcrypt.checkpw(digest, password_hash.encode("ascii"))
    except (TypeError, ValueError):
        return False


def issue_seller_token(seller_id: int) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": str(seller_id), "role": "seller", "iat": now, "exp": now + timedelta(hours=12)},
        settings.jwt_secret,
        algorithm="HS256",
    )


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=12 * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


async def current_seller(
    seller_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
    session: AsyncSession = Depends(get_session),
) -> Seller:
    if not seller_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="ورود لازم است.")
    try:
        payload = jwt.decode(seller_session, settings.jwt_secret, algorithms=["HS256"])
        if payload.get("role") != "seller":
            raise ValueError
        seller_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="نشست معتبر نیست.")
    seller = (
        await session.execute(
            select(Seller).where(Seller.id == seller_id, Seller.is_active.is_(True))
        )
    ).scalar_one_or_none()
    if seller is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="حساب غیرفعال است.")
    return seller


def _bearer_value(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Admin authentication required")
    return authorization.split(" ", 1)[1].strip()


async def current_admin(authorization: str | None = Header(default=None)) -> dict:
    token = _bearer_value(authorization)
    try:
        payload = jwt.decode(token, settings.admin_jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid admin token")
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin token required")
    permissions = {
        item.strip()
        for item in str(payload.get("perms") or "").split(",")
        if item.strip()
    }
    if not payload.get("owner") and "all" not in permissions and "sellers" not in permissions:
        raise HTTPException(status_code=403, detail="Seller management permission required")
    return payload
