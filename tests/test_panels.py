from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.panels import (
    MEXICO_UNLIMITED_DATA_LIMIT_BYTES,
    Panel,
    _api_base_url,
    _provider_data_limit,
    _recover_created_user,
)


def panel(key: str = "mexico_namahdod") -> Panel:
    return Panel(
        key=key,
        title="Test",
        panel_type="pasarguard",
        base_url="https://provider.example",
        username="user",
        password="pass",
        group_ids=[7],
        inbounds={},
        protocols=[],
        hwid_limit=1,
    )


class _Response:
    status_code = 200
    is_error = False

    def json(self):
        return {"username": "created", "subscription_url": "/sub/created"}


class _Client:
    async def get(self, _url, *, headers):
        return _Response()


class PanelRoutingTests(unittest.IsolatedAsyncioTestCase):
    def test_mexico_unlimited_keeps_provider_safety_cap(self) -> None:
        self.assertEqual(
            _provider_data_limit(panel(), 0),
            MEXICO_UNLIMITED_DATA_LIMIT_BYTES,
        )
        self.assertEqual(_provider_data_limit(panel("mmd_germany"), 10), 10 * 1024**3)

    def test_mexico_api_can_use_private_relay_without_changing_public_panel_url(self) -> None:
        value = panel()
        with patch("backend.panels.settings.mexico_panel_api_url", "https://relay.example/"):
            self.assertEqual(_api_base_url(value), "https://relay.example")
        self.assertEqual(value.base_url, "https://provider.example")

    async def test_timed_out_creation_can_recover_existing_panel_user(self) -> None:
        payload = await _recover_created_user(_Client(), {"Authorization": "Bearer token"}, "created")
        self.assertEqual(payload["username"], "created")


if __name__ == "__main__":
    unittest.main()
