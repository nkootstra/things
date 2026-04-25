"""Thin HTTP client for things-api."""

from __future__ import annotations

import os

import httpx


class ThingsAPIClient:
    """Wraps the things-api HTTP endpoints."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get("THINGS_API_URL", "http://localhost:8000")).rstrip("/")
        self.api_key = api_key or os.environ.get("THINGS_API_KEY", "")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"X-API-Key": self.api_key},
            timeout=30.0,
        )

    async def close(self) -> None:
        await self._client.aclose()

    # --- Helpers ---

    async def _get(self, path: str, params: dict | None = None) -> list | dict:
        resp = await self._client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    async def _post(self, path: str, json: dict) -> dict:
        resp = await self._client.post(path, json=json)
        resp.raise_for_status()
        return resp.json()

    async def _patch(self, path: str, json: dict) -> dict:
        resp = await self._client.patch(path, json=json)
        resp.raise_for_status()
        return resp.json()

    async def _delete(self, path: str) -> None:
        resp = await self._client.delete(path)
        resp.raise_for_status()

    # --- Smart lists ---

    async def list_inbox(self, limit: int | None = None, offset: int | None = None) -> list:
        return await self._get("/api/tasks/inbox", _pagination(limit, offset))

    async def list_today(self, limit: int | None = None, offset: int | None = None) -> list:
        return await self._get("/api/tasks/today", _pagination(limit, offset))

    async def list_upcoming(self, limit: int | None = None, offset: int | None = None) -> list:
        return await self._get("/api/tasks/upcoming", _pagination(limit, offset))

    async def list_anytime(self, limit: int | None = None, offset: int | None = None) -> list:
        return await self._get("/api/tasks/anytime", _pagination(limit, offset))

    async def list_someday(self, limit: int | None = None, offset: int | None = None) -> list:
        return await self._get("/api/tasks/someday", _pagination(limit, offset))

    async def list_logbook(self, since: float | None = None, limit: int | None = None) -> list:
        params: dict = {}
        if since is not None:
            params["since"] = since
        if limit is not None:
            params["limit"] = limit
        return await self._get("/api/tasks/logbook", params or None)

    async def list_trash(self, limit: int | None = None) -> list:
        params: dict = {}
        if limit is not None:
            params["limit"] = limit
        return await self._get("/api/tasks/trash", params or None)

    # --- Tasks ---

    async def get_task(self, uuid: str) -> dict:
        return await self._get(f"/api/tasks/{uuid}")

    async def list_tasks(self) -> list:
        return await self._get("/api/tasks")

    async def create_task(self, payload: dict) -> dict:
        return await self._post("/api/tasks", payload)

    async def update_task(self, uuid: str, payload: dict) -> dict:
        return await self._patch(f"/api/tasks/{uuid}", payload)

    async def delete_task(self, uuid: str) -> None:
        await self._delete(f"/api/tasks/{uuid}")

    # --- Tags ---

    async def list_tags(self) -> list:
        return await self._get("/api/tags")

    async def create_tag(self, payload: dict) -> dict:
        return await self._post("/api/tags", payload)

    async def list_tasks_by_tag(self, tag: str, include_descendants: bool = True) -> list:
        params = {"include_descendants": str(include_descendants).lower()}
        return await self._get(f"/api/tasks/by-tag/{tag}", params)

    # --- Areas & Projects ---

    async def list_areas(self) -> list:
        return await self._get("/api/areas")

    async def list_projects(self) -> list:
        """List projects (type=1 tasks)."""
        tasks = await self._get("/api/tasks")
        return [t for t in tasks if t.get("type") == "project"]

    # --- Sync ---

    async def trigger_sync(self) -> dict:
        return await self._post("/api/sync", {})


def _pagination(limit: int | None, offset: int | None) -> dict | None:
    params: dict = {}
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    return params or None
