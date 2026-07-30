from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.database import Base
from backend.models import Seller, SellerLedger, SellerOffer, SellerService
from backend.panels import Panel, PanelError
from backend.schemas import CreateServiceBody, ServiceRenewBody, ServiceUpdateBody
from backend.security import hash_password
from backend.service import (
    create_service,
    dashboard,
    remove_service,
    renew_service,
    update_service,
)


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

    async def test_per_gb_offer_charges_selected_volume(self) -> None:
        payload = {
            "username": "SellerVIP1",
            "status": "active",
            "used_traffic": 0,
            "data_limit": 10 * 1024**3,
            "expire": 1_900_000_000,
            "_subscription_url": "https://panel.example/sub/per-gb",
        }
        body = CreateServiceBody(
            request_id="per-gb-service-00000000000001",
            offer_id=self.offer_id,
            volume_gb=10,
            duration_days=30,
            time_mode="date",
        )
        async with self.sessions() as session:
            offer = await session.get(SellerOffer, self.offer_id)
            offer.pricing_mode = "per_gb"
            offer.price_per_gb_toman = 2_500
            await session.commit()
            seller = await session.get(Seller, self.seller_id)
            with (
                patch("backend.service.get_panel", return_value=self.panel),
                patch("backend.service.create_user", AsyncMock(return_value=payload)) as provision,
                patch("backend.service.sync_subscription", AsyncMock()),
                patch("backend.service.notify_service_created", AsyncMock()),
            ):
                service = await create_service(session, seller, body)

            await session.refresh(seller)
            self.assertEqual(service.volume_gb, 10)
            self.assertEqual(service.price_toman, 25_000)
            self.assertEqual(seller.wallet_balance, 475_000)
            self.assertEqual(provision.await_args.kwargs["volume_gb"], 10)
            ledger = list((await session.execute(select(SellerLedger))).scalars())
            self.assertEqual(len(ledger), 1)
            self.assertEqual(ledger[0].amount, -25_000)

    async def test_offer_minimum_volume_and_duration_are_enforced(self) -> None:
        async with self.sessions() as session:
            offer = await session.get(SellerOffer, self.offer_id)
            offer.pricing_mode = "per_gb"
            offer.price_per_gb_toman = 3_000
            offer.min_volume_gb = 10
            offer.min_duration_days = 7
            await session.commit()
            seller = await session.get(Seller, self.seller_id)

            with self.assertRaises(HTTPException) as volume_error:
                await create_service(
                    session,
                    seller,
                    CreateServiceBody(
                        request_id="minimum-volume-000000000001",
                        offer_id=self.offer_id,
                        volume_gb=5,
                        duration_days=30,
                        time_mode="date",
                    ),
                )
            self.assertEqual(volume_error.exception.status_code, 400)
            self.assertIn("10", volume_error.exception.detail)

            with self.assertRaises(HTTPException) as duration_error:
                await create_service(
                    session,
                    seller,
                    CreateServiceBody(
                        request_id="minimum-duration-000000001",
                        offer_id=self.offer_id,
                        volume_gb=10,
                        duration_days=3,
                        time_mode="date",
                    ),
                )
            self.assertEqual(duration_error.exception.status_code, 400)
            self.assertIn("7", duration_error.exception.detail)
            await session.refresh(seller)
            self.assertEqual(seller.wallet_balance, 500_000)

    async def test_panel_failure_cancels_charge_without_ledger_rows(self) -> None:
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
            self.assertEqual(values, [])
            values = await dashboard(session, seller.id)
            self.assertEqual(values["monthly_spend"], 0)

    async def test_subscription_failure_removes_provisioned_user_and_charge(self) -> None:
        payload = {
            "username": "SyncFailureUser",
            "status": "active",
            "used_traffic": 0,
            "data_limit": 20 * 1024**3,
            "expire": 1_900_000_000,
            "_subscription_url": "https://panel.example/sub/sync-failure",
        }
        body = CreateServiceBody(
            request_id="sync-failure-00000000000001",
            offer_id=self.offer_id,
            panel_username="SyncFailureUser",
            duration_days=30,
            time_mode="date",
        )
        async with self.sessions() as session:
            seller = await session.get(Seller, self.seller_id)
            with (
                patch("backend.service.get_panel", return_value=self.panel),
                patch(
                    "backend.service.fetch_user",
                    AsyncMock(return_value={"status": "deleted"}),
                ),
                patch("backend.service.create_user", AsyncMock(return_value=payload)),
                patch(
                    "backend.service.sync_subscription",
                    AsyncMock(side_effect=RuntimeError("sync unavailable")),
                ),
                patch("backend.service.delete_user", AsyncMock()) as remove_provider_user,
            ):
                with self.assertRaises(RuntimeError):
                    await create_service(session, seller, body)

            remove_provider_user.assert_awaited_once_with(self.panel, "SyncFailureUser")
            await session.refresh(seller)
            self.assertEqual(seller.wallet_balance, 500_000)
            self.assertEqual(
                list((await session.execute(select(SellerLedger))).scalars()),
                [],
            )
            self.assertEqual(
                list((await session.execute(select(SellerService))).scalars()),
                [],
            )
            values = await dashboard(session, seller.id)
            self.assertEqual(values["monthly_spend"], 0)

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

    async def test_explicit_duplicate_username_is_rejected_before_charge(self) -> None:
        body = CreateServiceBody(
            request_id="duplicate-user-0000000000001",
            offer_id=self.offer_id,
            panel_username="TakenUser",
            duration_days=30,
            time_mode="date",
        )
        async with self.sessions() as session:
            seller = await session.get(Seller, self.seller_id)
            with (
                patch("backend.service.get_panel", return_value=self.panel),
                patch(
                    "backend.service.fetch_user",
                    AsyncMock(return_value={"status": "active"}),
                ),
                patch("backend.service.create_user", AsyncMock()) as provision,
            ):
                with self.assertRaises(HTTPException) as raised:
                    await create_service(session, seller, body)
            self.assertEqual(raised.exception.status_code, 409)
            self.assertIn("TakenUser", raised.exception.detail)
            provision.assert_not_awaited()
            await session.refresh(seller)
            self.assertEqual(seller.wallet_balance, 500_000)

    async def test_allowed_debt_can_cross_zero(self) -> None:
        payload = {
            "username": "DebtUser",
            "status": "active",
            "used_traffic": 0,
            "data_limit": 20 * 1024**3,
            "expire": 1_900_000_000,
            "_subscription_url": "https://panel.example/sub/debt",
        }
        body = CreateServiceBody(
            request_id="debt-service-00000000000001",
            offer_id=self.offer_id,
            panel_username="DebtUser",
            duration_days=30,
            time_mode="date",
        )
        async with self.sessions() as session:
            seller = await session.get(Seller, self.seller_id)
            seller.wallet_balance = 0
            seller.allow_negative_balance = True
            await session.commit()
            with (
                patch("backend.service.get_panel", return_value=self.panel),
                patch(
                    "backend.service.fetch_user",
                    AsyncMock(return_value={"status": "deleted"}),
                ),
                patch("backend.service.create_user", AsyncMock(return_value=payload)),
                patch("backend.service.sync_subscription", AsyncMock()),
                patch("backend.service.notify_service_created", AsyncMock()),
            ):
                await create_service(session, seller, body)
            await session.refresh(seller)
            self.assertEqual(seller.wallet_balance, -100_000)

    async def test_locked_offer_uses_its_fixed_time_values(self) -> None:
        payload = {
            "username": "FixedTimeUser",
            "status": "active",
            "used_traffic": 0,
            "data_limit": 20 * 1024**3,
            "expire": 1_900_000_000,
            "_subscription_url": "https://panel.example/sub/fixed-time",
        }
        body = CreateServiceBody(
            request_id="fixed-time-00000000000000001",
            offer_id=self.offer_id,
            panel_username="FixedTimeUser",
            duration_days=7,
            time_mode="on_hold",
        )
        async with self.sessions() as session:
            offer = await session.get(SellerOffer, self.offer_id)
            offer.lock_time_mode = True
            offer.lock_duration = True
            await session.commit()
            seller = await session.get(Seller, self.seller_id)
            with (
                patch("backend.service.get_panel", return_value=self.panel),
                patch(
                    "backend.service.fetch_user",
                    AsyncMock(return_value={"status": "deleted"}),
                ),
                patch("backend.service.create_user", AsyncMock(return_value=payload)) as provision,
                patch("backend.service.sync_subscription", AsyncMock()),
                patch("backend.service.notify_service_created", AsyncMock()),
            ):
                service = await create_service(session, seller, body)

            self.assertEqual(service.duration_days, 30)
            self.assertEqual(service.time_mode, "date")
            self.assertEqual(provision.await_args.kwargs["duration_days"], 30)
            self.assertEqual(provision.await_args.kwargs["time_mode"], "date")

    async def test_time_mode_and_duration_locks_are_independent(self) -> None:
        async with self.sessions() as session:
            offer = await session.get(SellerOffer, self.offer_id)
            offer.lock_time_mode = True
            offer.lock_duration = False
            await session.commit()
            seller = await session.get(Seller, self.seller_id)
            payload = {
                "username": "ModeLocked",
                "status": "active",
                "used_traffic": 0,
                "data_limit": 20 * 1024**3,
                "expire": 1_900_000_000,
                "_subscription_url": "https://panel.example/sub/mode-locked",
            }
            with (
                patch("backend.service.get_panel", return_value=self.panel),
                patch("backend.service.fetch_user", AsyncMock(return_value={"status": "deleted"})),
                patch("backend.service.create_user", AsyncMock(return_value=payload)),
                patch("backend.service.sync_subscription", AsyncMock()),
                patch("backend.service.notify_service_created", AsyncMock()),
            ):
                service = await create_service(
                    session,
                    seller,
                    CreateServiceBody(
                        request_id="mode-locked-000000000000001",
                        offer_id=self.offer_id,
                        panel_username="ModeLocked",
                        duration_days=7,
                        time_mode="on_hold",
                    ),
                )
            self.assertEqual(service.time_mode, "date")
            self.assertEqual(service.duration_days, 7)

        async with self.sessions() as session:
            offer = await session.get(SellerOffer, self.offer_id)
            offer.lock_time_mode = False
            offer.lock_duration = True
            await session.commit()
            seller = await session.get(Seller, self.seller_id)
            payload = {
                "username": "DurationLocked",
                "status": "on_hold",
                "used_traffic": 0,
                "data_limit": 20 * 1024**3,
                "expire": 0,
                "_subscription_url": "https://panel.example/sub/duration-locked",
            }
            with (
                patch("backend.service.get_panel", return_value=self.panel),
                patch("backend.service.fetch_user", AsyncMock(return_value={"status": "deleted"})),
                patch("backend.service.create_user", AsyncMock(return_value=payload)),
                patch("backend.service.sync_subscription", AsyncMock()),
                patch("backend.service.notify_service_created", AsyncMock()),
            ):
                service = await create_service(
                    session,
                    seller,
                    CreateServiceBody(
                        request_id="duration-locked-00000000001",
                        offer_id=self.offer_id,
                        panel_username="DurationLocked",
                        duration_days=7,
                        time_mode="on_hold",
                    ),
                )
            self.assertEqual(service.time_mode, "on_hold")
            self.assertEqual(service.duration_days, 30)

    async def test_locked_volume_cannot_be_changed_after_creation(self) -> None:
        async with self.sessions() as session:
            offer = await session.get(SellerOffer, self.offer_id)
            offer.lock_volume = True
            service = SellerService(
                request_id="locked-volume-service-000001",
                seller_id=self.seller_id,
                offer_id=self.offer_id,
                panel_key="easy",
                panel_username="LockedVolume",
                upstream_url="https://panel.example/sub/locked-volume",
                public_token="locked-volume-token",
                public_url="https://api.example/token/locked-volume-token",
                volume_gb=20,
                duration_days=30,
                time_mode="date",
                price_toman=100_000,
            )
            session.add(service)
            await session.commit()

            with self.assertRaises(HTTPException) as raised:
                await update_service(
                    session,
                    service,
                    ServiceUpdateBody(volume_gb=30, duration_days=30, time_mode="date"),
                )
            self.assertEqual(raised.exception.status_code, 403)

    async def test_remove_deletes_provider_subscription_and_local_row(self) -> None:
        async with self.sessions() as session:
            seller = await session.get(Seller, self.seller_id)
            seller.wallet_balance = 400_000
            service = SellerService(
                request_id="remove-service-000000000001",
                seller_id=self.seller_id,
                offer_id=self.offer_id,
                panel_key="easy",
                panel_username="RemoveMe",
                upstream_url="https://panel.example/sub/remove",
                public_token="remove-token",
                public_url="https://api.example/token/remove-token",
                volume_gb=20,
                duration_days=30,
                time_mode="date",
                price_toman=100_000,
            )
            session.add(service)
            await session.flush()
            ledger = SellerLedger(
                seller_id=self.seller_id,
                amount=-100_000,
                balance_after=400_000,
                kind="purchase",
                description="خرید سرویس حذف‌شونده",
                service_id=service.id,
            )
            session.add(ledger)
            await session.commit()
            await session.refresh(service)
            service_id = service.id
            ledger_id = ledger.id
            with (
                patch("backend.service.get_panel", return_value=self.panel),
                patch("backend.service.delete_user", AsyncMock()) as provider_delete,
                patch("backend.service.delete_subscription", AsyncMock()) as sub_delete,
            ):
                await remove_service(session, service)
            provider_delete.assert_awaited_once()
            sub_delete.assert_awaited_once()
            self.assertIsNone(await session.get(SellerService, service_id))
            await session.refresh(seller)
            self.assertEqual(seller.wallet_balance, 400_000)
            preserved_ledger = await session.get(SellerLedger, ledger_id)
            self.assertIsNotNone(preserved_ledger)
            self.assertEqual(preserved_ledger.amount, -100_000)
            self.assertIsNone(preserved_ledger.service_id)

    async def test_edit_updates_provider_cache_and_subscription(self) -> None:
        async with self.sessions() as session:
            service = SellerService(
                request_id="edit-service-00000000000001",
                seller_id=self.seller_id,
                offer_id=self.offer_id,
                panel_key="easy",
                panel_username="EditMe",
                upstream_url="https://panel.example/sub/edit",
                public_token="edit-token",
                public_url="https://api.example/token/edit-token",
                volume_gb=20,
                duration_days=30,
                time_mode="date",
                price_toman=100_000,
            )
            session.add(service)
            await session.commit()
            await session.refresh(service)
            body = ServiceUpdateBody(volume_gb=50, duration_days=45, time_mode="date")
            with (
                patch("backend.service.get_panel", return_value=self.panel),
                patch(
                    "backend.service.update_user",
                    AsyncMock(
                        return_value={
                            "status": "active",
                            "data_limit": 50 * 1024**3,
                            "expire": 1_950_000_000,
                        }
                    ),
                ) as provider_update,
                patch("backend.service.sync_subscription", AsyncMock()) as sub_sync,
            ):
                updated = await update_service(session, service, body)
            provider_update.assert_awaited_once()
            sub_sync.assert_awaited_once()
            self.assertEqual(updated.volume_gb, 50)
            self.assertEqual(updated.duration_days, 45)
            self.assertEqual(updated.data_limit_bytes, 50 * 1024**3)

    async def test_per_gb_volume_increase_charges_only_difference(self) -> None:
        async with self.sessions() as session:
            offer = await session.get(SellerOffer, self.offer_id)
            offer.pricing_mode = "per_gb"
            offer.price_per_gb_toman = 2_500
            service = SellerService(
                request_id="resize-service-0000000000001",
                seller_id=self.seller_id,
                offer_id=self.offer_id,
                panel_key="easy",
                panel_username="ResizeMe",
                upstream_url="https://panel.example/sub/resize",
                public_token="resize-token",
                public_url="https://api.example/token/resize-token",
                volume_gb=20,
                duration_days=30,
                time_mode="date",
                price_toman=50_000,
                used_bytes=5 * 1024**3,
                data_limit_bytes=20 * 1024**3,
            )
            session.add(service)
            await session.commit()
            with (
                patch("backend.service.get_panel", return_value=self.panel),
                patch(
                    "backend.service.update_user",
                    AsyncMock(return_value={"data_limit": 30 * 1024**3}),
                ) as provider_update,
                patch("backend.service.sync_subscription", AsyncMock()),
            ):
                updated = await update_service(
                    session,
                    service,
                    ServiceUpdateBody(volume_gb=30, duration_days=30, time_mode="date"),
                )

            seller = await session.get(Seller, self.seller_id)
            self.assertEqual(seller.wallet_balance, 475_000)
            self.assertEqual(updated.volume_gb, 30)
            self.assertEqual(updated.price_toman, 75_000)
            self.assertFalse(provider_update.await_args.kwargs["update_timing"])
            ledgers = list((await session.execute(select(SellerLedger))).scalars())
            self.assertEqual(len(ledgers), 1)
            self.assertEqual(ledgers[0].amount, -25_000)
            self.assertEqual(ledgers[0].kind, "volume_adjustment")

    async def test_volume_cannot_be_reduced_below_consumed_traffic(self) -> None:
        async with self.sessions() as session:
            offer = await session.get(SellerOffer, self.offer_id)
            offer.pricing_mode = "per_gb"
            offer.price_per_gb_toman = 2_500
            service = SellerService(
                request_id="reduce-service-0000000000001",
                seller_id=self.seller_id,
                offer_id=self.offer_id,
                panel_key="easy",
                panel_username="ReduceMe",
                upstream_url="https://panel.example/sub/reduce",
                public_token="reduce-token",
                public_url="https://api.example/token/reduce-token",
                volume_gb=20,
                duration_days=30,
                time_mode="date",
                price_toman=50_000,
                used_bytes=15 * 1024**3,
                data_limit_bytes=20 * 1024**3,
            )
            session.add(service)
            await session.commit()
            with (
                patch("backend.service.get_panel", return_value=self.panel),
                patch(
                    "backend.service.fetch_user",
                    AsyncMock(return_value={"used_traffic": 15 * 1024**3}),
                ),
                patch("backend.service.update_user", AsyncMock()) as provider_update,
            ):
                with self.assertRaises(HTTPException) as raised:
                    await update_service(
                        session,
                        service,
                        ServiceUpdateBody(volume_gb=10, duration_days=30, time_mode="date"),
                    )

            self.assertEqual(raised.exception.status_code, 409)
            provider_update.assert_not_awaited()
            seller = await session.get(Seller, self.seller_id)
            self.assertEqual(seller.wallet_balance, 500_000)

    async def test_edit_cannot_go_below_offer_minimums(self) -> None:
        async with self.sessions() as session:
            offer = await session.get(SellerOffer, self.offer_id)
            offer.pricing_mode = "per_gb"
            offer.price_per_gb_toman = 3_000
            offer.min_volume_gb = 10
            offer.min_duration_days = 7
            service = SellerService(
                request_id="minimum-edit-00000000000001",
                seller_id=self.seller_id,
                offer_id=self.offer_id,
                panel_key="easy",
                panel_username="MinimumEdit",
                upstream_url="https://panel.example/sub/minimum-edit",
                public_token="minimum-edit-token",
                public_url="https://api.example/token/minimum-edit-token",
                volume_gb=20,
                duration_days=30,
                time_mode="date",
                price_toman=60_000,
                used_bytes=2 * 1024**3,
                data_limit_bytes=20 * 1024**3,
            )
            session.add(service)
            await session.commit()

            with self.assertRaises(HTTPException) as volume_error:
                await update_service(
                    session,
                    service,
                    ServiceUpdateBody(volume_gb=9, duration_days=30, time_mode="date"),
                )
            self.assertEqual(volume_error.exception.status_code, 400)

            with self.assertRaises(HTTPException) as duration_error:
                await update_service(
                    session,
                    service,
                    ServiceUpdateBody(volume_gb=20, duration_days=6, time_mode="date"),
                )
            self.assertEqual(duration_error.exception.status_code, 400)

    async def test_renewal_charges_resets_usage_and_is_idempotent(self) -> None:
        async with self.sessions() as session:
            offer = await session.get(SellerOffer, self.offer_id)
            offer.pricing_mode = "per_gb"
            offer.price_per_gb_toman = 2_500
            service = SellerService(
                request_id="renew-service-00000000000001",
                seller_id=self.seller_id,
                offer_id=self.offer_id,
                panel_key="easy",
                panel_username="RenewMe",
                upstream_url="https://panel.example/sub/renew",
                public_token="renew-token",
                public_url="https://api.example/token/renew-token",
                volume_gb=20,
                duration_days=30,
                time_mode="date",
                price_toman=50_000,
                used_bytes=19 * 1024**3,
                data_limit_bytes=20 * 1024**3,
            )
            session.add(service)
            await session.commit()
            body = ServiceRenewBody(request_id="renew-operation-000000000001")
            with (
                patch("backend.service.get_panel", return_value=self.panel),
                patch("backend.service.update_user", AsyncMock(return_value={})),
                patch(
                    "backend.service.reset_user_traffic",
                    AsyncMock(
                        return_value={
                            "status": "active",
                            "used_traffic": 0,
                            "data_limit": 20 * 1024**3,
                            "expire": 1_950_000_000,
                        }
                    ),
                ) as reset_traffic,
                patch(
                    "backend.service.fetch_user",
                    AsyncMock(
                        return_value={
                            "status": "active",
                            "used_traffic": 0,
                            "data_limit": 20 * 1024**3,
                            "expire": 1_950_000_000,
                        }
                    ),
                ),
            ):
                renewed = await renew_service(session, service, body)
                repeated = await renew_service(session, service, body)

            self.assertEqual(renewed.id, repeated.id)
            self.assertEqual(reset_traffic.await_count, 1)
            self.assertEqual(renewed.used_bytes, 0)
            seller = await session.get(Seller, self.seller_id)
            self.assertEqual(seller.wallet_balance, 450_000)
            ledgers = list((await session.execute(select(SellerLedger))).scalars())
            self.assertEqual(len(ledgers), 1)
            self.assertEqual(ledgers[0].kind, "renewal")
            self.assertEqual(ledgers[0].amount, -50_000)


if __name__ == "__main__":
    unittest.main()
