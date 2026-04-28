"""Service-layer protocol contracts for dependency inversion."""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession


class SyncServiceProtocol(Protocol):
    async def get_status(self, session: AsyncSession) -> dict: ...

    async def trigger_manual_sync(self, session: AsyncSession) -> dict: ...


class TaskServiceProtocol(Protocol):
    async def list_tasks(
        self,
        session: AsyncSession,
        *,
        tag: str | None = None,
        include_descendants: bool = True,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict]: ...

    async def get_task(self, session: AsyncSession, uuid: str) -> dict: ...

    async def get_task_checklist(self, session: AsyncSession, uuid: str) -> list[dict]: ...

    async def list_areas(self, session: AsyncSession) -> list[dict]: ...

    async def list_tags(self, session: AsyncSession) -> list[dict]: ...

    async def create_task(self, session: AsyncSession, **payload) -> dict: ...

    async def update_task(self, session: AsyncSession, uuid: str, updates: dict) -> dict: ...

    async def delete_task(self, session: AsyncSession, uuid: str) -> None: ...

    async def create_checklist_item(self, session: AsyncSession, *, task_uuid: str, title: str) -> dict: ...

    async def complete_checklist_item(self, session: AsyncSession, uuid: str) -> dict: ...

    async def uncomplete_checklist_item(self, session: AsyncSession, uuid: str) -> dict: ...

    # Smart lists
    async def list_inbox(self, session: AsyncSession, *, limit: int | None = None, offset: int | None = None) -> list[dict]: ...

    async def list_today(self, session: AsyncSession, *, limit: int | None = None, offset: int | None = None) -> list[dict]: ...

    async def list_upcoming(self, session: AsyncSession, *, limit: int | None = None, offset: int | None = None) -> list[dict]: ...

    async def list_anytime(self, session: AsyncSession, *, limit: int | None = None, offset: int | None = None) -> list[dict]: ...

    async def list_someday(self, session: AsyncSession, *, limit: int | None = None, offset: int | None = None) -> list[dict]: ...

    async def list_logbook(self, session: AsyncSession, *, since: float | None = None, limit: int | None = 100, offset: int | None = None) -> list[dict]: ...

    async def list_trash(self, session: AsyncSession, *, limit: int | None = 100, offset: int | None = None) -> list[dict]: ...

    async def list_projects(
        self,
        session: AsyncSession,
        *,
        include_completed: bool = False,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict]: ...

    async def search_tasks(
        self,
        session: AsyncSession,
        *,
        query: str,
        include_trashed: bool = False,
        include_checklists: bool = True,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict]: ...

    async def search_advanced(
        self,
        session: AsyncSession,
        *,
        status: int | None = None,
        type: int | None = None,
        schedule: int | None = None,
        area_uuid: str | None = None,
        project_uuid: str | None = None,
        tag: str | None = None,
        include_descendants: bool = True,
        start_date_from: float | None = None,
        start_date_to: float | None = None,
        deadline_from: float | None = None,
        deadline_to: float | None = None,
        modified_since: float | None = None,
        completed_since: float | None = None,
        include_trashed: bool = False,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict]: ...


class TagServiceProtocol(Protocol):
    async def create_tag(self, session: AsyncSession, *, title: str, parent: str | None = None, shortcut: str | None = None) -> dict: ...

    async def update_tag(self, session: AsyncSession, uuid: str, **kwargs) -> dict: ...

    async def delete_tag(self, session: AsyncSession, uuid: str) -> None: ...

    async def list_tags(self, session: AsyncSession) -> list[dict]: ...

    async def get_tag(self, session: AsyncSession, uuid: str) -> dict: ...


class TaskCommandMapperProtocol(Protocol):
    def to_create_payload(self, body, *, status_enum, schedule_enum, type_enum) -> dict: ...

    def to_update_payload(self, updates: dict, *, status_enum, schedule_enum, type_enum) -> dict: ...
