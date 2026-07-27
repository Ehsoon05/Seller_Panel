from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.database_url)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def initialize_database() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

        def migrate(sync_connection) -> None:
            seller_columns = {
                column["name"] for column in inspect(sync_connection).get_columns("sellers")
            }
            if "allow_negative_balance" not in seller_columns:
                sync_connection.execute(
                    text(
                        "ALTER TABLE sellers ADD COLUMN "
                        "allow_negative_balance BOOLEAN NOT NULL DEFAULT 0"
                    )
                )
            offer_columns = {
                column["name"] for column in inspect(sync_connection).get_columns("seller_offers")
            }
            if "lock_volume" not in offer_columns:
                sync_connection.execute(
                    text(
                        "ALTER TABLE seller_offers ADD COLUMN "
                        "lock_volume BOOLEAN NOT NULL DEFAULT 0"
                    )
                )
            if "lock_time" not in offer_columns:
                sync_connection.execute(
                    text(
                        "ALTER TABLE seller_offers ADD COLUMN "
                        "lock_time BOOLEAN NOT NULL DEFAULT 0"
                    )
                )

        await connection.run_sync(migrate)
