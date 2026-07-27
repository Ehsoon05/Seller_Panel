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
            columns = {
                column["name"] for column in inspect(sync_connection).get_columns("sellers")
            }
            if "allow_negative_balance" not in columns:
                sync_connection.execute(
                    text(
                        "ALTER TABLE sellers ADD COLUMN "
                        "allow_negative_balance BOOLEAN NOT NULL DEFAULT 0"
                    )
                )

        await connection.run_sync(migrate)
