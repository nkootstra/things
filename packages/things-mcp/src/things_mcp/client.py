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

    async def list_tasks(self, limit: int | None = None, offset: int | None = None) -> list:
        return await self._get("/api/tasks", _pagination(limit, offset))

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

    async def list_tasks_by_tag(
        self,
        tag: str,
        include_descendants: bool = True,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list:
        params: dict = {"include_descendants": str(include_descendants).lower()}
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        return await self._get(f"/api/tasks/by-tag/{tag}", params)

    # --- Areas & Projects ---

    async def list_areas(self) -> list:
        return await self._get("/api/areas")

    async def list_projects(
        self,
        include_completed: bool = False,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list:
        params: dict = {"include_completed": str(include_completed).lower()}
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        return await self._get("/api/projects", params)

    async def create_project(self, payload: dict) -> dict:
        return await self._post("/api/projects", payload)

    async def update_project(self, uuid: str, payload: dict) -> dict:
        return await self._patch(f"/api/projects/{uuid}", payload)

    async def complete_project(self, uuid: str) -> dict:
        return await self._post(f"/api/projects/{uuid}/complete", {})

    async def delete_project(self, uuid: str) -> None:
        await self._delete(f"/api/projects/{uuid}")

    # --- Search ---

    async def search_tasks(
        self,
        query: str,
        include_trashed: bool = False,
        include_checklists: bool = True,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list:
        params: dict = {
            "q": query,
            "include_trashed": str(include_trashed).lower(),
            "include_checklists": str(include_checklists).lower(),
        }
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        return await self._get("/api/tasks/search", params)

    async def search_advanced(self, **kwargs) -> list:
        params: dict = {}
        for key, value in kwargs.items():
            if value is None:
                continue
            params[key] = str(value).lower() if isinstance(value, bool) else value
        return await self._get("/api/tasks/search/advanced", params or None)

    # --- Sync ---

    async def trigger_sync(self) -> dict:
        return await self._post("/api/sync", {})

    # --- Checklist items ---

    async def create_checklist_item(self, task_uuid: str, title: str) -> dict:
        return await self._post(f"/api/tasks/{task_uuid}/checklist", {"title": title})

    async def complete_checklist_item(self, uuid: str) -> dict:
        return await self._post(f"/api/checklist/{uuid}/complete", {})

    async def uncomplete_checklist_item(self, uuid: str) -> dict:
        return await self._post(f"/api/checklist/{uuid}/uncomplete", {})


def _pagination(limit: int | None, offset: int | None) -> dict | None:
    params: dict = {}
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    return params or None
