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
            if "pricing_mode" not in offer_columns:
                sync_connection.execute(
                    text(
                        "ALTER TABLE seller_offers ADD COLUMN "
                        "pricing_mode VARCHAR(20) NOT NULL DEFAULT 'fixed'"
                    )
                )
            if "price_per_gb_toman" not in offer_columns:
                sync_connection.execute(
                    text(
                        "ALTER TABLE seller_offers ADD COLUMN "
                        "price_per_gb_toman BIGINT NOT NULL DEFAULT 0"
                    )
                )
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
            if "lock_time_mode" not in offer_columns:
                sync_connection.execute(
                    text(
                        "ALTER TABLE seller_offers ADD COLUMN "
                        "lock_time_mode BOOLEAN NOT NULL DEFAULT 0"
                    )
                )
                sync_connection.execute(
                    text(
                        "UPDATE seller_offers SET lock_time_mode = lock_time "
                        "WHERE lock_time = 1"
                    )
                )
            if "lock_duration" not in offer_columns:
                sync_connection.execute(
                    text(
                        "ALTER TABLE seller_offers ADD COLUMN "
                        "lock_duration BOOLEAN NOT NULL DEFAULT 0"
                    )
                )
                sync_connection.execute(
                    text(
                        "UPDATE seller_offers SET lock_duration = lock_time "
                        "WHERE lock_time = 1"
                    )
                )
            ledger_columns = {
                column["name"] for column in inspect(sync_connection).get_columns("seller_ledger")
            }
            if "operation_id" not in ledger_columns:
                sync_connection.execute(
                    text("ALTER TABLE seller_ledger ADD COLUMN operation_id VARCHAR(80)")
                )
                sync_connection.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS "
                        "ix_seller_ledger_operation_id ON seller_ledger (operation_id)"
                    )
                )

        await connection.run_sync(migrate)
