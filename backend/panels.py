from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

from .config import settings


class PanelError(RuntimeError):
    pass


@dataclass(frozen=True)
class Panel:
    key: str
    title: str
    panel_type: str
    base_url: str
    username: str
    password: str
    group_ids: list[int]
    inbounds: dict[str, list[str]]
    protocols: list[str]
    hwid_limit: int | None


def _json(value: str | None, fallback):
    try:
        parsed = json.loads(value or "")
    except ValueError:
        return fallback
    return parsed if isinstance(parsed, type(fallback)) else fallback


def list_panels() -> list[Panel]:
    path = Path(settings.phantom_database_path)
    if not path.exists():
        raise PanelError("دیتابیس پنل‌های ساخت در دسترس نیست.")
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT key,title,panel_type,base_url,username,password,group_ids,"
            "inbounds_json,protocols_json,hwid_limit FROM provision_panels "
            "WHERE is_enabled = 1 ORDER BY title"
        ).fetchall()
    finally:
        connection.close()
    return [
        Panel(
            key=row["key"],
            title=row["title"],
            panel_type=row["panel_type"],
            base_url=row["base_url"].rstrip("/"),
            username=row["username"],
            password=row["password"],
            group_ids=[int(item) for item in _json(row["group_ids"], []) if str(item).isdigit()],
            inbounds=_json(row["inbounds_json"], {}),
            protocols=[str(item) for item in _json(row["protocols_json"], [])],
            hwid_limit=row["hwid_limit"],
        )
        for row in rows
    ]


def get_panel(key: str) -> Panel:
    panel = next((item for item in list_panels() if item.key == key), None)
    if panel is None:
        raise PanelError("پنل ساخت فعال پیدا نشد.")
    return panel


def _error(response: httpx.Response, action: str) -> PanelError:
    detail = response.text.strip()[:350]
    return PanelError(f"{action} انجام نشد: HTTP {response.status_code} - {detail}")


def _api_base_url(panel: Panel) -> str:
    if panel.key == "svn" and settings.svn_panel_api_url:
        return settings.svn_panel_api_url.rstrip("/")
    return panel.base_url


async def _token(client: httpx.AsyncClient, panel: Panel) -> str:
    try:
        response = await client.post(
            "/api/admin/token",
            data={"username": panel.username, "password": panel.password},
        )
    except httpx.HTTPError as exc:
        raise PanelError("ارتباط با پنل ساخت برقرار نشد.") from exc
    if response.is_error:
        raise _error(response, "ورود به پنل")
    try:
        token = response.json().get("access_token")
    except ValueError as exc:
        raise PanelError("پاسخ ورود پنل معتبر نیست.") from exc
    if not token:
        raise PanelError("پنل توکن دسترسی برنگرداند.")
    return str(token)


def _timing(mode: str, duration_days: int) -> dict[str, Any]:
    if mode == "unlimited" or duration_days == 0:
        return {"status": "active", "expire": 0, "on_hold_expire_duration": None}
    if mode == "on_hold":
        return {
            "status": "on_hold",
            "expire": 0,
            "on_hold_expire_duration": duration_days * 86400,
        }
    return {
        "status": "active",
        "expire": int((datetime.now(timezone.utc) + timedelta(days=duration_days)).timestamp()),
        "on_hold_expire_duration": None,
    }


def _subscription_url(base_url: str, payload: dict[str, Any]) -> str:
    value = str(payload.get("subscription_url") or "").strip()
    if not value:
        raise PanelError("پنل لینک اشتراک برنگرداند.")
    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        value = urlunparse(("", "", parsed.path, parsed.params, parsed.query, parsed.fragment))
    return urljoin(f"{base_url.rstrip('/')}/", value)


async def _access_fields(
    client: httpx.AsyncClient,
    panel: Panel,
    headers: dict[str, str],
    hwid_limit: int | None,
) -> dict[str, Any]:
    grouped = panel.panel_type in {"easy", "pasarguard"}
    fields: dict[str, Any] = {}
    if grouped:
        group_ids = panel.group_ids or ([] if panel.panel_type == "pasarguard" else [1])
        if group_ids:
            fields["group_ids"] = group_ids
        limit = hwid_limit if hwid_limit is not None else panel.hwid_limit
        if limit is not None and limit > 0:
            fields["hwid_limit"] = limit
        if panel.panel_type == "easy":
            return fields
    if panel.inbounds:
        return {
            **fields,
            "proxies": {protocol: {} for protocol in panel.inbounds},
            "inbounds": panel.inbounds,
        }
    response = await client.get("/api/inbounds", headers=headers)
    if response.is_error:
        if grouped:
            if panel.protocols:
                fields["proxies"] = {protocol: {} for protocol in panel.protocols}
            return fields
        raise _error(response, "دریافت اینباندها")
    payload = response.json()
    inbounds: dict[str, list[str]] = {}
    if isinstance(payload, dict):
        for protocol, items in payload.items():
            if panel.protocols and protocol not in panel.protocols:
                continue
            tags = [
                str(item.get("tag"))
                for item in items
                if isinstance(item, dict) and item.get("tag")
            ] if isinstance(items, list) else []
            if tags:
                inbounds[str(protocol)] = tags
    elif isinstance(payload, list):
        tags = [str(item).strip() for item in payload if str(item).strip()]
        if tags:
            inbounds["vless"] = tags
    if not inbounds and not grouped:
        raise PanelError("هیچ اینباند فعالی پیدا نشد.")
    fields.update({"proxies": {key: {} for key in inbounds}, "inbounds": inbounds})
    return fields


async def create_user(
    panel: Panel,
    *,
    username: str,
    volume_gb: int,
    duration_days: int,
    time_mode: str,
    hwid_limit: int | None,
) -> dict[str, Any]:
    async with httpx.AsyncClient(
        base_url=_api_base_url(panel),
        verify=False,
        timeout=httpx.Timeout(40, connect=15),
    ) as client:
        token = await _token(client, panel)
        headers = {"Authorization": f"Bearer {token}"}
        access = await _access_fields(client, panel, headers, hwid_limit)
        response = await client.post(
            "/api/user",
            headers=headers,
            json={
                "username": username,
                "data_limit": volume_gb * 1024**3 if volume_gb > 0 else 0,
                "data_limit_reset_strategy": "no_reset",
                **_timing(time_mode, duration_days),
                **access,
            },
        )
        if response.is_error:
            raise _error(response, "ساخت سرویس")
        payload = response.json()
    payload["_subscription_url"] = _subscription_url(panel.base_url, payload)
    return payload


async def fetch_user(panel: Panel, username: str) -> dict[str, Any]:
    async with httpx.AsyncClient(
        base_url=_api_base_url(panel),
        verify=False,
        timeout=httpx.Timeout(30, connect=12),
    ) as client:
        token = await _token(client, panel)
        response = await client.get(
            f"/api/user/{username}",
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code == 404:
            return {"status": "deleted"}
        if response.is_error:
            raise _error(response, "دریافت وضعیت سرویس")
        return response.json()


async def set_user_status(panel: Panel, username: str, enabled: bool) -> str:
    status_value = "active" if enabled else "disabled"
    async with httpx.AsyncClient(
        base_url=_api_base_url(panel),
        verify=False,
        timeout=httpx.Timeout(30, connect=12),
    ) as client:
        token = await _token(client, panel)
        response = await client.put(
            f"/api/user/{username}",
            headers={"Authorization": f"Bearer {token}"},
            json={"status": status_value},
        )
        if response.is_error:
            raise _error(response, "تغییر وضعیت سرویس")
    return status_value


async def update_user(
    panel: Panel,
    *,
    username: str,
    volume_gb: int,
    duration_days: int,
    time_mode: str,
) -> dict[str, Any]:
    async with httpx.AsyncClient(
        base_url=_api_base_url(panel),
        verify=False,
        timeout=httpx.Timeout(40, connect=15),
    ) as client:
        token = await _token(client, panel)
        response = await client.put(
            f"/api/user/{username}",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "data_limit": volume_gb * 1024**3 if volume_gb > 0 else 0,
                "data_limit_reset_strategy": "no_reset",
                **_timing(time_mode, duration_days),
            },
        )
        if response.status_code == 404:
            raise PanelError("یوزرنیم کانفیگ در پنل سازنده پیدا نشد.")
        if response.is_error:
            raise _error(response, "ویرایش سرویس")
        try:
            payload = response.json()
        except ValueError:
            payload = {}
    return payload if isinstance(payload, dict) else {}


async def delete_user(panel: Panel, username: str) -> None:
    async with httpx.AsyncClient(
        base_url=_api_base_url(panel),
        verify=False,
        timeout=httpx.Timeout(30, connect=12),
    ) as client:
        token = await _token(client, panel)
        response = await client.delete(
            f"/api/user/{username}",
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code not in {200, 204, 404}:
            raise _error(response, "حذف سرویس ناقص")
