"""API-facing task service that adapts SDK errors to HTTP exceptions."""

from fastapi import HTTPException

from things_api.services.contracts import TaskServiceProtocol
from things_sdk import EntityNotFoundError
from things_sdk.tasks import TaskService as SDKTaskService


def _not_found(err: EntityNotFoundError) -> HTTPException:
    """Map an SDK EntityNotFoundError to an accurate 404.

    The SDK distinguishes Task vs Tag vs ChecklistItem via ``entity_name``;
    surface that to API callers instead of always saying "Task not found",
    which previously masked the real cause when, for example, a tag in
    ``GET /api/tasks/by-tag/{tag}`` did not exist.
    """
    return HTTPException(
        status_code=404,
        detail=f"{err.entity_name} not found: {err.identifier}",
    )


class TaskService(TaskServiceProtocol):
    def __init__(self) -> None:
        self._sdk = SDKTaskService()

    async def list_tasks(self, session, *, tag=None, include_descendants=True, limit=None, offset=None):
        try:
            return await self._sdk.list_tasks(
                session,
                tag=tag,
                include_descendants=include_descendants,
                limit=limit,
                offset=offset,
            )
        except EntityNotFoundError as e:
            raise _not_found(e)

    async def get_task(self, session, uuid: str):
        try:
            return await self._sdk.get_task(session, uuid)
        except EntityNotFoundError as e:
            raise _not_found(e)

    async def get_task_checklist(self, session, uuid: str):
        try:
            return await self._sdk.get_task_checklist(session, uuid)
        except EntityNotFoundError as e:
            raise _not_found(e)

    async def list_areas(self, session):
        return await self._sdk.list_areas(session)

    async def list_tags(self, session):
        return await self._sdk.list_tags(session)

    async def create_task(self, session, **payload):
        return await self._sdk.create_task(session, **payload)

    async def update_task(self, session, uuid: str, updates: dict):
        try:
            return await self._sdk.update_task(session, uuid, updates)
        except EntityNotFoundError as e:
            raise _not_found(e)

    async def delete_task(self, session, uuid: str) -> None:
        try:
            await self._sdk.delete_task(session, uuid)
        except EntityNotFoundError as e:
            raise _not_found(e)

    async def create_checklist_item(self, session, *, task_uuid, title):
        try:
            return await self._sdk.create_checklist_item(session, task_uuid=task_uuid, title=title)
        except EntityNotFoundError as e:
            raise _not_found(e)

    async def complete_checklist_item(self, session, uuid):
        try:
            return await self._sdk.complete_checklist_item(session, uuid)
        except EntityNotFoundError as e:
            raise _not_found(e)

    async def uncomplete_checklist_item(self, session, uuid):
        try:
            return await self._sdk.uncomplete_checklist_item(session, uuid)
        except EntityNotFoundError as e:
            raise _not_found(e)

    # Smart lists

    async def list_inbox(self, session, *, limit=None, offset=None):
        return await self._sdk.list_inbox(session, limit=limit, offset=offset)

    async def list_today(self, session, *, limit=None, offset=None):
        return await self._sdk.list_today(session, limit=limit, offset=offset)

    async def list_upcoming(self, session, *, limit=None, offset=None):
        return await self._sdk.list_upcoming(session, limit=limit, offset=offset)

    async def list_anytime(self, session, *, limit=None, offset=None):
        return await self._sdk.list_anytime(session, limit=limit, offset=offset)

    async def list_someday(self, session, *, limit=None, offset=None):
        return await self._sdk.list_someday(session, limit=limit, offset=offset)

    async def list_logbook(self, session, *, since=None, limit=100, offset=None):
        return await self._sdk.list_logbook(session, since=since, limit=limit, offset=offset)

    async def list_trash(self, session, *, limit=100, offset=None):
        return await self._sdk.list_trash(session, limit=limit, offset=offset)

    async def list_projects(self, session, *, include_completed=False, limit=None, offset=None):
        return await self._sdk.list_projects(
            session,
            include_completed=include_completed,
            limit=limit,
            offset=offset,
        )

    async def search_tasks(
        self,
        session,
        *,
        query,
        include_trashed=False,
        include_checklists=True,
        limit=None,
        offset=None,
    ):
        return await self._sdk.search_tasks(
            session,
            query=query,
            include_trashed=include_trashed,
            include_checklists=include_checklists,
            limit=limit,
            offset=offset,
        )

    async def search_advanced(self, session, **kwargs):
        try:
            return await self._sdk.search_advanced(session, **kwargs)
        except EntityNotFoundError as e:
            raise _not_found(e)


def get_task_service() -> TaskServiceProtocol:
    return TaskService()
