from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Seller(Base):
    __tablename__ = "sellers"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    wallet_balance: Mapped[int] = mapped_column(BigInteger, default=0)
    allow_negative_balance: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    offers: Mapped[list["SellerOffer"]] = relationship(
        back_populates="seller", cascade="all, delete-orphan"
    )
    services: Mapped[list["SellerService"]] = relationship(back_populates="seller")


class SellerOffer(Base):
    __tablename__ = "seller_offers"
    __table_args__ = (UniqueConstraint("seller_id", "title", name="uq_seller_offer_title"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("sellers.id"), index=True)
    title: Mapped[str] = mapped_column(String(140))
    panel_key: Mapped[str] = mapped_column(String(80), index=True)
    price_toman: Mapped[int] = mapped_column(BigInteger)
    volume_gb: Mapped[int] = mapped_column(Integer, default=0)
    lock_volume: Mapped[bool] = mapped_column(Boolean, default=False)
    default_duration_days: Mapped[int] = mapped_column(Integer, default=30)
    allowed_time_modes_json: Mapped[str] = mapped_column(Text, default='["date"]')
    default_time_mode: Mapped[str] = mapped_column(String(20), default="date")
    lock_time: Mapped[bool] = mapped_column(Boolean, default=False)
    name_prefix: Mapped[str] = mapped_column(String(120), default="PhantomSeller_1")
    next_sequence: Mapped[int] = mapped_column(Integer, default=1)
    panel_hwid_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subscription_device_limit: Mapped[int] = mapped_column(Integer, default=0)
    profile_title: Mapped[str | None] = mapped_column(String(160), nullable=True)
    support_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    show_header: Mapped[bool] = mapped_column(Boolean, default=True)
    show_config_preview: Mapped[bool] = mapped_column(Boolean, default=True)
    info_proxies_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    seller: Mapped[Seller] = relationship(back_populates="offers")


class SellerService(Base):
    __tablename__ = "seller_services"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("sellers.id"), index=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("seller_offers.id"), index=True)
    panel_key: Mapped[str] = mapped_column(String(80), index=True)
    panel_username: Mapped[str] = mapped_column(String(120), index=True)
    display_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    upstream_url: Mapped[str] = mapped_column(Text)
    public_token: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    public_url: Mapped[str] = mapped_column(Text)
    volume_gb: Mapped[int] = mapped_column(Integer, default=0)
    duration_days: Mapped[int] = mapped_column(Integer, default=0)
    time_mode: Mapped[str] = mapped_column(String(20))
    price_toman: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(30), default="active")
    used_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    data_limit_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    online_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    seller: Mapped[Seller] = relationship(back_populates="services")
    offer: Mapped[SellerOffer] = relationship()


class SellerLedger(Base):
    __tablename__ = "seller_ledger"

    id: Mapped[int] = mapped_column(primary_key=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("sellers.id"), index=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    balance_after: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(30))
    description: Mapped[str] = mapped_column(String(300))
    service_id: Mapped[int | None] = mapped_column(ForeignKey("seller_services.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
