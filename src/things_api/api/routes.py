"""API endpoints for Things3 data."""

from enum import IntEnum

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from things_api.auth import require_api_key
from things_api.db.engine import get_session
from things_api.services.contracts import (
    SyncServiceProtocol,
    TaskCommandMapperProtocol,
    TaskServiceProtocol,
)
from things_api.services.sync_service import get_sync_service
from things_api.services.task_command_mapper import get_task_command_mapper
from things_api.services.task_service import get_task_service

router = APIRouter(prefix="/api", dependencies=[Depends(require_api_key)])


# --- Enums ---

class TaskStatus(IntEnum):
    pending = 0
    cancelled = 2
    completed = 3


class TaskSchedule(IntEnum):
    inbox = 0
    anytime = 1
    someday = 2


class TaskType(IntEnum):
    task = 0
    project = 1
    heading = 2



@router.get("/tasks")
async def list_tasks(
    session: AsyncSession = Depends(get_session),
    task_service: TaskServiceProtocol = Depends(get_task_service),
):
    return await task_service.list_tasks(session)


@router.get("/tasks/{uuid}")
async def get_task(
    uuid: str,
    session: AsyncSession = Depends(get_session),
    task_service: TaskServiceProtocol = Depends(get_task_service),
):
    return await task_service.get_task(session, uuid)


@router.get("/tasks/{uuid}/checklist")
async def get_task_checklist(
    uuid: str,
    session: AsyncSession = Depends(get_session),
    task_service: TaskServiceProtocol = Depends(get_task_service),
):
    return await task_service.get_task_checklist(session, uuid)


@router.get("/areas")
async def list_areas(
    session: AsyncSession = Depends(get_session),
    task_service: TaskServiceProtocol = Depends(get_task_service),
):
    return await task_service.list_areas(session)


@router.get("/tags")
async def list_tags(
    session: AsyncSession = Depends(get_session),
    task_service: TaskServiceProtocol = Depends(get_task_service),
):
    return await task_service.list_tags(session)


@router.get("/sync/status")
async def sync_status(
    session: AsyncSession = Depends(get_session),
    sync_service: SyncServiceProtocol = Depends(get_sync_service),
):
    return await sync_service.get_status(session)


@router.post("/sync")
async def trigger_sync(
    session: AsyncSession = Depends(get_session),
    sync_service: SyncServiceProtocol = Depends(get_sync_service),
):
    """Manually trigger a full pull + push sync cycle."""
    return await sync_service.trigger_manual_sync(session)


# --- Write endpoints ---


class TaskCreate(BaseModel):
    title: str
    notes: str | None = None
    status: int | str = 0
    schedule: int | str = 0
    type: int | str = 0
    area_uuid: str | None = None
    project_uuid: str | None = None
    heading_uuid: str | None = None
    deadline: float | None = None
    start_date: float | None = None
    reminder_time: int | None = None


class TaskUpdate(BaseModel):
    title: str | None = None
    notes: str | None = None
    status: int | str | None = None
    schedule: int | str | None = None
    type: int | str | None = None
    area_uuid: str | None = None
    project_uuid: str | None = None
    heading_uuid: str | None = None
    deadline: float | None = None
    start_date: float | None = None
    reminder_time: int | None = None


@router.post("/tasks", status_code=201)
async def create_task(
    body: TaskCreate,
    session: AsyncSession = Depends(get_session),
    task_service: TaskServiceProtocol = Depends(get_task_service),
    mapper: TaskCommandMapperProtocol = Depends(get_task_command_mapper),
):
    payload = mapper.to_create_payload(
        body,
        status_enum=TaskStatus,
        schedule_enum=TaskSchedule,
        type_enum=TaskType,
    )
    return await task_service.create_task(session, **payload)


@router.patch("/tasks/{uuid}")
async def update_task(
    uuid: str,
    body: TaskUpdate,
    session: AsyncSession = Depends(get_session),
    task_service: TaskServiceProtocol = Depends(get_task_service),
    mapper: TaskCommandMapperProtocol = Depends(get_task_command_mapper),
):
    updates = mapper.to_update_payload(
        body.model_dump(exclude_unset=True),
        status_enum=TaskStatus,
        schedule_enum=TaskSchedule,
        type_enum=TaskType,
    )
    return await task_service.update_task(session, uuid, updates)


@router.delete("/tasks/{uuid}", status_code=204)
async def delete_task(
    uuid: str,
    session: AsyncSession = Depends(get_session),
    task_service: TaskServiceProtocol = Depends(get_task_service),
):
    await task_service.delete_task(session, uuid)
    return Response(status_code=204)
