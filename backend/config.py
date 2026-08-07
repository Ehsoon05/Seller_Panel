from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./seller_panel.db"
    phantom_database_path: str = "/opt/phantom/bot_data.db"
    svn_panel_api_url: str = ""
    mexico_panel_api_url: str = ""
    jwt_secret: str
    admin_jwt_secret: str
    subscription_sync_url: str = Field(
        default="",
        validation_alias=AliasChoices(
            "SUBSCRIPTION_SYNC_URL",
            "SUBSCRIPTION_PANEL_SYNC_URL",
        ),
    )
    subscription_sync_token: str = Field(
        default="",
        validation_alias=AliasChoices(
            "SUBSCRIPTION_SYNC_TOKEN",
            "SUBSCRIPTION_PANEL_SYNC_TOKEN",
        ),
    )
    subscription_public_base_url: str = "https://api.phantomhubs.shop"
    cors_origins: str = "https://sellers.phantomhubs.shop,https://admin.phantomhubs.shop"
    cookie_secure: bool = True
    notification_bot_token: str = ""
    notification_chat_ids: str = ""

    @property
    def allowed_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def notification_recipients(self) -> list[int]:
        return [
            int(item.strip())
            for item in self.notification_chat_ids.split(",")
            if item.strip().lstrip("-").isdigit()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
