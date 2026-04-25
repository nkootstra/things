"""API-facing task service that adapts SDK errors to HTTP exceptions."""

from fastapi import HTTPException

from things_api.services.contracts import TaskServiceProtocol
from things_sdk import EntityNotFoundError
from things_sdk.tasks import TaskService as SDKTaskService


class TaskService(TaskServiceProtocol):
    def __init__(self) -> None:
        self._sdk = SDKTaskService()

    async def list_tasks(self, session):
        return await self._sdk.list_tasks(session)

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


def get_task_service() -> TaskServiceProtocol:
    return TaskService()
