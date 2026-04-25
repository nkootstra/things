"""Things Cloud HTTP client and authentication."""

from __future__ import annotations

from urllib.parse import quote

import httpx

BASE_URL = "https://cloud.culturedcode.com"
DEFAULT_HEADERS = {
    "App-Id": "com.culturedcode.ThingsMac",
    "Schema": "301",
}


class ThingsCloudAuthError(Exception):
    pass


class ThingsCloudClient:
    """Async HTTP client for the Things Cloud API."""

    def __init__(self, email: str, password: str) -> None:
        self.email = email
        self.password = password
        self.history_key: str | None = None
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=BASE_URL,
                headers=DEFAULT_HEADERS,
                timeout=30.0,
            )
        return self._client

    async def authenticate(self) -> str:
        """Authenticate with Things Cloud and return the history key."""
        client = await self._get_client()
        encoded_password = quote(self.password, safe="")

        resp = await client.get(
            f"/version/1/account/{quote(self.email, safe='')}",
            headers={"Authorization": f"Password {encoded_password}"},
        )

        if resp.status_code == 404:
            raise ThingsCloudAuthError("Account not found")
        if resp.status_code == 401:
            raise ThingsCloudAuthError("Invalid password")
        resp.raise_for_status()

        data = resp.json()
        self.history_key = data.get("history-key") or data.get("SYServerHistoryKeyKey")
        if not self.history_key:
            raise ThingsCloudAuthError("No history key in account response")

        return self.history_key

    async def get_items(self, start_index: int = 0) -> tuple[list[dict], int]:
        """Fetch all sync items from Things Cloud, handling pagination."""
        if not self.history_key:
            await self.authenticate()

        client = await self._get_client()
        encoded_password = quote(self.password, safe="")

        all_items: list[dict] = []
        current_start = start_index

        while True:
            resp = await client.get(
                f"/version/1/history/{self.history_key}/items",
                params={"start-index": current_start},
                headers={"Authorization": f"Password {encoded_password}"},
            )
            resp.raise_for_status()

            data = resp.json()
            items = data.get("items", [])
            current_index = data.get("current-item-index", current_start)

            all_items.extend(items)

            # If we got no items or current_index didn't advance, we're done
            if not items or current_index <= current_start + len(items):
                return all_items, current_index

            # More pages available
            current_start = current_start + len(items)

    async def commit(self, items: list[dict], ancestor_index: int) -> int:
        """Push changes to Things Cloud."""
        if not self.history_key:
            await self.authenticate()

        client = await self._get_client()
        encoded_password = quote(self.password, safe="")

        resp = await client.post(
            f"/version/1/history/{self.history_key}/commit",
            params={"ancestor-index": ancestor_index},
            json=items,
            headers={
                "Authorization": f"Password {encoded_password}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()

        data = resp.json()
        return data.get("server-head-index", ancestor_index + len(items))

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
