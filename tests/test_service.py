from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.database import Base
from backend.models import Seller, SellerLedger, SellerOffer, SellerService
from backend.panels import Panel, PanelError
from backend.schemas import CreateServiceBody
from backend.security import hash_password
from backend.service import create_service, dashboard


class SellerServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.temp.name}/seller.db")
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with self.sessions() as session:
            seller = Seller(
                username="partner",
                display_name="Partner",
                password_hash=hash_password("StrongPassword"),
                wallet_balance=500_000,
            )
            session.add(seller)
            await session.flush()
            offer = SellerOffer(
                seller_id=seller.id,
                title="20 GB",
                panel_key="easy",
                price_toman=100_000,
                volume_gb=20,
                default_duration_days=30,
                allowed_time_modes_json='["date","on_hold"]',
                default_time_mode="date",
                name_prefix="SellerVIP1",
                next_sequence=1,
            )
            session.add(offer)
            await session.commit()
            self.seller_id = seller.id
            self.offer_id = offer.id
        self.panel = Panel(
            key="easy",
            title="Easy",
            panel_type="easy",
            base_url="https://panel.example",
            username="admin",
            password="secret",
            group_ids=[1],
            inbounds={},
            protocols=[],
            hwid_limit=1,
        )

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.temp.cleanup()

    async def test_successful_build_is_charged_once_and_idempotent(self) -> None:
        payload = {
            "username": "SellerVIP1",
            "status": "active",
            "used_traffic": 0,
            "data_limit": 20 * 1024**3,
            "expire": 1_900_000_000,
            "_subscription_url": "https://panel.example/sub/token",
        }
        body = CreateServiceBody(
            request_id="12345678-1234-1234-1234-123456789012",
            offer_id=self.offer_id,
            display_name="Customer one",
            duration_days=30,
            time_mode="date",
        )
        async with self.sessions() as session:
            seller = await session.get(Seller, self.seller_id)
            with (
                patch("backend.service.get_panel", return_value=self.panel),
                patch("backend.service.create_user", AsyncMock(return_value=payload)) as provision,
                patch("backend.service.sync_subscription", AsyncMock()),
            ):
                first = await create_service(session, seller, body)
                second = await create_service(session, seller, body)

            self.assertEqual(first.id, second.id)
            self.assertEqual(provision.await_count, 1)
            await session.refresh(seller)
            self.assertEqual(seller.wallet_balance, 400_000)
            services = list((await session.execute(select(SellerService))).scalars())
            self.assertEqual(len(services), 1)
            ledger = list((await session.execute(select(SellerLedger))).scalars())
            self.assertEqual(len(ledger), 1)
            self.assertEqual(ledger[0].amount, -100_000)

    async def test_panel_failure_refunds_wallet(self) -> None:
        body = CreateServiceBody(
            request_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            offer_id=self.offer_id,
            duration_days=30,
            time_mode="date",
        )
        async with self.sessions() as session:
            seller = await session.get(Seller, self.seller_id)
            with (
                patch("backend.service.get_panel", return_value=self.panel),
                patch(
                    "backend.service.create_user",
                    AsyncMock(side_effect=PanelError("panel unavailable")),
                ),
            ):
                with self.assertRaises(PanelError):
                    await create_service(session, seller, body)
            await session.refresh(seller)
            self.assertEqual(seller.wallet_balance, 500_000)
            values = list((await session.execute(select(SellerLedger))).scalars())
            self.assertEqual([row.amount for row in values], [-100_000, 100_000])

    async def test_dashboard_reads_cached_values_only(self) -> None:
        async with self.sessions() as session:
            session.add(
                SellerService(
                    request_id="dashboard-service-0001",
                    seller_id=self.seller_id,
                    offer_id=self.offer_id,
                    panel_key="easy",
                    panel_username="SellerVIP1",
                    upstream_url="https://panel.example/sub/token",
                    public_token="public-token",
                    public_url="https://api.example/token/public-token",
                    volume_gb=20,
                    duration_days=30,
                    time_mode="date",
                    price_toman=100_000,
                    status="active",
                    used_bytes=1024,
                    data_limit_bytes=20 * 1024**3,
                )
            )
            await session.commit()
            value = await dashboard(session, self.seller_id)
        self.assertEqual(value["total_services"], 1)
        self.assertEqual(value["active_services"], 1)
        self.assertEqual(value["used_bytes"], 1024)


if __name__ == "__main__":
    unittest.main()

