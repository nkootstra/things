"""API-facing task service that adapts SDK errors to HTTP exceptions."""

from fastapi import HTTPException

from things_api.services.contracts import TaskServiceProtocol
from things_sdk import EntityNotFoundError
from things_sdk.tasks import TaskService as SDKTaskService


class TaskService(TaskServiceProtocol):
    def __init__(self) -> None:
        self._sdk = SDKTaskService()

    async def list_tasks(self, session, *, tag=None, include_descendants=True):
        return await self._sdk.list_tasks(session, tag=tag, include_descendants=include_descendants)

    async def get_task(self, session, uuid: str):
        try:
            return await self._sdk.get_task(session, uuid)
        except EntityNotFoundError:
            raise HTTPException(status_code=404, detail="Task not found")

    async def get_task_checklist(self, session, uuid: str):
        try:
            return await self._sdk.get_task_checklist(session, uuid)
        except EntityNotFoundError:
            raise HTTPException(status_code=404, detail="Task not found")

    async def list_areas(self, session):
        return await self._sdk.list_areas(session)

    async def list_tags(self, session):
        return await self._sdk.list_tags(session)

    async def create_task(self, session, **payload):
        return await self._sdk.create_task(session, **payload)

    async def update_task(self, session, uuid: str, updates: dict):
        try:
            return await self._sdk.update_task(session, uuid, updates)
        except EntityNotFoundError:
            raise HTTPException(status_code=404, detail="Task not found")

    async def delete_task(self, session, uuid: str) -> None:
        try:
            await self._sdk.delete_task(session, uuid)
        except EntityNotFoundError:
            raise HTTPException(status_code=404, detail="Task not found")

    async def create_checklist_item(self, session, *, task_uuid, title):
        try:
            return await self._sdk.create_checklist_item(session, task_uuid=task_uuid, title=title)
        except EntityNotFoundError:
            raise HTTPException(status_code=404, detail="Task not found")

    async def complete_checklist_item(self, session, uuid):
        try:
            return await self._sdk.complete_checklist_item(session, uuid)
        except EntityNotFoundError:
            raise HTTPException(status_code=404, detail="Checklist item not found")

    async def uncomplete_checklist_item(self, session, uuid):
        try:
            return await self._sdk.uncomplete_checklist_item(session, uuid)
        except EntityNotFoundError:
            raise HTTPException(status_code=404, detail="Checklist item not found")

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


def get_task_service() -> TaskServiceProtocol:
    return TaskService()
