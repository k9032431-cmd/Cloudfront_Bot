"""Асинхронный клиент Cloudflare API v4 (на aiohttp, который уже есть в aiogram).

Авторизация: API Token (рекомендуется) или Global API Key + email.
Документация: https://developers.cloudflare.com/api/
"""
from dataclasses import dataclass
from typing import Any

import aiohttp

API_URL = "https://api.cloudflare.com/client/v4"
TIMEOUT = aiohttp.ClientTimeout(total=30)


class CfError(Exception):
    pass


@dataclass
class Page:
    items: list[dict]
    page: int
    total_pages: int
    total: int


class CloudflareAPI:
    def __init__(self, token: str = "", email: str = "", global_key: str = ""):
        if token:
            self._headers = {"Authorization": f"Bearer {token}"}
        else:
            self._headers = {"X-Auth-Email": email, "X-Auth-Key": global_key}

    async def _request(self, method: str, path: str, *, params: dict | None = None,
                       json: Any = None, raw: bool = False) -> Any:
        try:
            async with aiohttp.ClientSession(timeout=TIMEOUT, headers=self._headers, trust_env=True) as s:
                async with s.request(method, API_URL + path, params=params, json=json) as resp:
                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        raise CfError(f"HTTP {resp.status}: некорректный ответ Cloudflare")
        except aiohttp.ClientError as e:
            raise CfError(f"Нет связи с Cloudflare: {e}") from e
        except TimeoutError as e:
            raise CfError("Cloudflare не ответил вовремя") from e
        if not isinstance(data, dict) or not data.get("success"):
            errors = data.get("errors") if isinstance(data, dict) else None
            msg = "; ".join(f"{e.get('code')}: {e.get('message')}" for e in errors or []) or f"HTTP {resp.status}"
            raise CfError(msg)
        return data if raw else data.get("result")

    async def _page(self, path: str, params: dict) -> Page:
        data = await self._request("GET", path, params=params, raw=True)
        info = data.get("result_info") or {}
        return Page(
            items=data.get("result") or [],
            page=info.get("page", 1),
            total_pages=max(info.get("total_pages", 1) or 1, 1),
            total=info.get("total_count", len(data.get("result") or [])),
        )

    # ---------- Аккаунт ----------

    async def verify(self) -> tuple[str, str]:
        """Проверяет доступ. Возвращает (account_id, account_name); id может быть пустым."""
        try:
            accounts = await self._request("GET", "/accounts", params={"per_page": 5})
        except CfError:
            accounts = []
        zones = await self._request("GET", "/zones", params={"per_page": 1})  # проверка прав на зоны
        if accounts:
            return accounts[0]["id"], accounts[0].get("name", "")
        if zones:
            acc = zones[0].get("account") or {}
            return acc.get("id", ""), acc.get("name", "")
        return "", ""

    # ---------- Зоны (домены) ----------

    async def list_zones(self, page: int = 1, per_page: int = 20) -> Page:
        return await self._page("/zones", {"page": page, "per_page": per_page, "order": "name"})

    async def get_zone(self, zone_id: str) -> dict:
        return await self._request("GET", f"/zones/{zone_id}")

    async def create_zone(self, name: str, account_id: str) -> dict:
        return await self._request("POST", "/zones", json={
            "name": name, "account": {"id": account_id}, "type": "full", "jump_start": True,
        })

    async def delete_zone(self, zone_id: str) -> None:
        await self._request("DELETE", f"/zones/{zone_id}")

    async def activation_check(self, zone_id: str) -> None:
        await self._request("PUT", f"/zones/{zone_id}/activation_check")

    async def purge_cache(self, zone_id: str) -> None:
        await self._request("POST", f"/zones/{zone_id}/purge_cache", json={"purge_everything": True})

    async def get_settings(self, zone_id: str) -> dict[str, Any]:
        items = await self._request("GET", f"/zones/{zone_id}/settings")
        return {i["id"]: i.get("value") for i in items or []}

    async def set_setting(self, zone_id: str, name: str, value: Any) -> None:
        await self._request("PATCH", f"/zones/{zone_id}/settings/{name}", json={"value": value})

    # ---------- DNS ----------

    async def list_records(self, zone_id: str, page: int = 1, per_page: int = 20) -> Page:
        return await self._page(f"/zones/{zone_id}/dns_records",
                                {"page": page, "per_page": per_page, "order": "type"})

    async def find_record(self, zone_id: str, prefix: str) -> dict | None:
        """Ищет запись по началу ID (в кнопках Telegram полный ID не помещается)."""
        page = 1
        while True:
            p = await self._page(f"/zones/{zone_id}/dns_records", {"page": page, "per_page": 500})
            for r in p.items:
                if r["id"].startswith(prefix):
                    return r
            if page >= p.total_pages:
                return None
            page += 1

    async def create_record(self, zone_id: str, record: dict) -> dict:
        return await self._request("POST", f"/zones/{zone_id}/dns_records", json=record)

    async def update_record(self, zone_id: str, record_id: str, changes: dict) -> dict:
        return await self._request("PATCH", f"/zones/{zone_id}/dns_records/{record_id}", json=changes)

    async def delete_record(self, zone_id: str, record_id: str) -> None:
        await self._request("DELETE", f"/zones/{zone_id}/dns_records/{record_id}")
