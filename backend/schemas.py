from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator


class LoginBody(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=6, max_length=128)


class CreateServiceBody(BaseModel):
    request_id: str = Field(pattern=r"^[A-Za-z0-9-]{16,80}$")
    offer_id: int
    panel_username: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9_-]{3,120}$",
    )
    display_name: str | None = Field(default=None, max_length=160)
    volume_gb: int | None = Field(default=None, ge=0, le=100000)
    duration_days: int | None = Field(default=None, ge=0, le=3650)
    time_mode: str | None = None


class ServiceUpdateBody(BaseModel):
    volume_gb: int = Field(ge=0, le=100000)
    duration_days: int = Field(ge=0, le=3650)
    time_mode: str


class ServiceRenewBody(BaseModel):
    request_id: str = Field(pattern=r"^[A-Za-z0-9-]{16,80}$")


class SellerCreateBody(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z0-9_.-]{3,80}$")
    display_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    initial_balance: int = 0
    allow_negative_balance: bool = False
    is_active: bool = True


class SellerUpdateBody(BaseModel):
    username: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9_.-]{3,80}$",
    )
    display_name: str | None = Field(default=None, min_length=2, max_length=120)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    allow_negative_balance: bool | None = None
    is_active: bool | None = None


class BalanceBody(BaseModel):
    amount: int
    description: str = Field(default="اصلاح موجودی توسط مدیر", max_length=300)


class OfferBody(BaseModel):
    title: str = Field(min_length=2, max_length=140)
    panel_key: str = Field(min_length=1, max_length=80)
    price_toman: int = Field(ge=0)
    pricing_mode: str = "fixed"
    price_per_gb_toman: int = Field(default=0, ge=0)
    volume_gb: int = Field(ge=0, le=100000)
    min_volume_gb: int = Field(default=0, ge=0, le=100000)
    lock_volume: bool = False
    default_duration_days: int = Field(default=30, ge=0, le=3650)
    min_duration_days: int = Field(default=1, ge=0, le=3650)
    allowed_time_modes: list[str] = Field(default_factory=lambda: ["date"])
    default_time_mode: str = "date"
    lock_time_mode: bool = False
    lock_duration: bool = False
    name_prefix: str = Field(default="PhantomSeller_1", min_length=1, max_length=120)
    panel_hwid_limit: int | None = Field(default=None, ge=0, le=1000)
    subscription_device_limit: int = Field(default=0, ge=0, le=1000)
    profile_title: str | None = Field(default=None, max_length=160)
    support_url: str | None = Field(default=None, max_length=500)
    show_header: bool = True
    show_config_preview: bool = True
    info_proxies_enabled: bool = False
    is_active: bool = True

    @field_validator("pricing_mode")
    @classmethod
    def validate_pricing_mode(cls, value: str) -> str:
        if value not in {"fixed", "per_gb"}:
            raise ValueError("Pricing mode must be fixed or per_gb")
        return value

    @field_validator("allowed_time_modes")
    @classmethod
    def validate_modes(cls, value: list[str]) -> list[str]:
        allowed = {"date", "on_hold", "unlimited"}
        normalized = list(dict.fromkeys(item for item in value if item in allowed))
        if not normalized:
            raise ValueError("At least one time mode is required")
        return normalized

    @model_validator(mode="after")
    def validate_plan_limits(self):
        minimum_volume = max(1, self.min_volume_gb) if self.pricing_mode == "per_gb" else self.min_volume_gb
        if self.volume_gb < minimum_volume:
            raise ValueError("Default volume cannot be lower than minimum volume")
        if (
            self.default_time_mode != "unlimited"
            and self.default_duration_days < self.min_duration_days
        ):
            raise ValueError("Default duration cannot be lower than minimum duration")
        return self
