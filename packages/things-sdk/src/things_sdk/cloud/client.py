"""Things Cloud HTTP client and authentication."""

from __future__ import annotations

import base64
import json
import logging
import os
import uuid as uuid_mod
import zlib
from urllib.parse import quote

from things_sdk.cloud.protocol import is_valid_things_uuid

import httpx

BASE_URL = "https://cloud.culturedcode.com"

# Client info matching Things3 Mac format
_CLIENT_INFO = base64.b64encode(json.dumps({
    "dm": "unknown",
    "lr": "US",
    "nf": True,
    "nk": True,
    "nn": "ThingsMac",
    "nv": "32211507",
    "on": "macOS",
    "ov": "14.0",
    "pl": "en",
    "ul": "en-Latn-US",
}, separators=(",", ":")).encode()).decode()

# Stable app instance ID (generated once, reused)
_APP_INSTANCE_ID = (
    uuid_mod.uuid5(uuid_mod.NAMESPACE_DNS, "things-sdk.local").hex
    + "-com.culturedcode.ThingsMac-"
    + uuid_mod.uuid5(uuid_mod.NAMESPACE_DNS, "things-sdk.instance").hex
)

DEFAULT_HEADERS = {
    "App-Id": "com.culturedcode.ThingsMac",
    "Schema": "301",
    "User-Agent": "ThingsMac/32211507",
    "Accept": "application/json",
    "Accept-Charset": "UTF-8",
    "Push-Priority": "5",
    "things-client-info": _CLIENT_INFO,
    "App-Instance-Id": _APP_INSTANCE_ID,
}

logger = logging.getLogger(__name__)


class ThingsCloudAuthError(Exception):
    pass


class ThingsCloudWriteRefused(Exception):
    """Raised when a commit is refused locally, before it is sent to Things Cloud."""


# Set THINGS_WRITE_FREEZE to a file path and create that file to refuse all writes.
# Unset (the default) leaves writes enabled.
WRITE_FREEZE_FILE = os.environ.get("THINGS_WRITE_FREEZE") or None


def _guard_commit(items: list[dict]) -> None:
    """Refuse commits that official clients cannot apply, or that crash Things.app.

    Cloud history is append-only: a bad item cannot be removed by a later commit.
    """
    if WRITE_FREEZE_FILE and os.path.exists(WRITE_FREEZE_FILE):
        raise ThingsCloudWriteRefused(f"Things Cloud writes frozen ({WRITE_FREEZE_FILE} exists)")
    seen = set()
    for item in items:
        for u, ch in item.items():
            if u in seen:
                raise ThingsCloudWriteRefused(f"duplicate id in commit: {u}")
            seen.add(u)
            if not is_valid_things_uuid(u):
                raise ThingsCloudWriteRefused(f"non-canonical Things id: {u}")
            p = ch.get("p") or {}
            for k in ("ar", "pr", "agr", "tg", "rt", "ts", "pn"):
                for r in p.get(k) or []:
                    if not is_valid_things_uuid(r):
                        raise ThingsCloudWriteRefused(f"non-canonical ref {k}={r} in {u}")
            if p.get("dloid") is not None and not is_valid_things_uuid(p["dloid"]):
                raise ThingsCloudWriteRefused(f"non-canonical tombstone target {p['dloid']}")
            for k in ("sr", "dd", "tir"):
                v = p.get(k)
                if v is not None and (not isinstance(v, int) or v % 86400):
                    raise ThingsCloudWriteRefused(f"{k}={v!r} not an int UTC-midnight day in {u}")
            if p.get("ss") in (2, 3) and "sp" in p and p["sp"] is None:
                raise ThingsCloudWriteRefused(f"completed/canceled without sp in {u}")
            # Official clients put a to-do in a project root or under a heading, never both.
            if p.get("pr") and p.get("agr"):
                raise ThingsCloudWriteRefused(f"both pr and agr set in {u}")
            nt = p.get("nt")
            if isinstance(nt, dict) and nt.get("t") == 1 and nt.get("v"):
                if nt.get("ch") != zlib.crc32(str(nt["v"]).encode("utf-8")):
                    raise ThingsCloudWriteRefused(f"notes checksum mismatch in {u} (the app would wipe the note)")


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
            server_schema = data.get("schema", None)

            if server_schema is not None:
                our_schema = int(DEFAULT_HEADERS["Schema"])
                if server_schema > our_schema:
                    logger.warning(
                        "Things Cloud reports schema version %s, but client uses %s. "
                        "Some new fields may not be synced correctly.",
                        server_schema,
                        our_schema,
                    )

            all_items.extend(items)

            # If we got no items or current_index didn't advance, we're done
            if not items or current_index <= current_start + len(items):
                return all_items, current_index

            # More pages available
            current_start = current_start + len(items)

    async def commit(self, items: list[dict], ancestor_index: int) -> int:
        """Push changes to Things Cloud.

        Items is a list of single-key dicts [{uuid: {t, e, p}}, ...].
        These are merged into a single flat dict for the commit body.
        """
        if not self.history_key:
            await self.authenticate()

        _guard_commit(items)
        client = await self._get_client()
        encoded_password = quote(self.password, safe="")

        # Merge list of single-key dicts into one flat dict
        body: dict = {}
        for item in items:
            body.update(item)

        resp = await client.post(
            f"/version/1/history/{self.history_key}/commit",
            params={"ancestor-index": ancestor_index, "_cnt": len(items)},
            json=body,
            headers={
                "Authorization": f"Password {encoded_password}",
                "Content-Type": "application/json; charset=UTF-8",
            },
        )
        resp.raise_for_status()

        data = resp.json()
        return data.get("server-head-index", ancestor_index + len(items))

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
