from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./seller_panel.db"
    phantom_database_path: str = "/opt/phantom/bot_data.db"
    svn_panel_api_url: str = ""
    jwt_secret: str
    admin_jwt_secret: str
    subscription_sync_url: str = ""
    subscription_sync_token: str = ""
    subscription_public_base_url: str = "https://api.phantomhubs.shop"
    cors_origins: str = "https://sellers.phantomhubs.shop,https://admin.phantomhubs.shop"
    cookie_secure: bool = True

    @property
    def allowed_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
