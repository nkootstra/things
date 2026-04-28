"""API endpoints for Things3 data."""

from enum import IntEnum

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from things_api.auth import require_api_key
from things_api.db.engine import get_session
from things_api.services.contracts import (
    SyncServiceProtocol,
    TagServiceProtocol,
    TaskCommandMapperProtocol,
    TaskServiceProtocol,
)
from things_api.services.sync_service import get_sync_service
from things_api.services.tag_service import get_tag_service
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


# --- Smart-list endpoints (must be before {uuid} catch-all) ---


@router.get("/tasks/inbox")
async def list_inbox(
    limit: int | None = None,
    offset: int | None = None,
    session: AsyncSession = Depends(get_session),
    task_service: TaskServiceProtocol = Depends(get_task_service),
):
    return await task_service.list_inbox(session, limit=limit, offset=offset)


@router.get("/tasks/today")
async def list_today(
    limit: int | None = None,
    offset: int | None = None,
    session: AsyncSession = Depends(get_session),
    task_service: TaskServiceProtocol = Depends(get_task_service),
):
    return await task_service.list_today(session, limit=limit, offset=offset)


@router.get("/tasks/upcoming")
async def list_upcoming(
    limit: int | None = None,
    offset: int | None = None,
    session: AsyncSession = Depends(get_session),
    task_service: TaskServiceProtocol = Depends(get_task_service),
):
    return await task_service.list_upcoming(session, limit=limit, offset=offset)


@router.get("/tasks/anytime")
async def list_anytime(
    limit: int | None = None,
    offset: int | None = None,
    session: AsyncSession = Depends(get_session),
    task_service: TaskServiceProtocol = Depends(get_task_service),
):
    return await task_service.list_anytime(session, limit=limit, offset=offset)


@router.get("/tasks/someday")
async def list_someday(
    limit: int | None = None,
    offset: int | None = None,
    session: AsyncSession = Depends(get_session),
    task_service: TaskServiceProtocol = Depends(get_task_service),
):
    return await task_service.list_someday(session, limit=limit, offset=offset)


@router.get("/tasks/logbook")
async def list_logbook(
    since: float | None = None,
    limit: int | None = 100,
    offset: int | None = None,
    session: AsyncSession = Depends(get_session),
    task_service: TaskServiceProtocol = Depends(get_task_service),
):
    return await task_service.list_logbook(session, since=since, limit=limit, offset=offset)


@router.get("/tasks/trash")
async def list_trash(
    limit: int | None = 100,
    offset: int | None = None,
    session: AsyncSession = Depends(get_session),
    task_service: TaskServiceProtocol = Depends(get_task_service),
):
    return await task_service.list_trash(session, limit=limit, offset=offset)


@router.get("/tasks/by-tag/{tag}")
async def list_tasks_by_tag(
    tag: str,
    include_descendants: bool = True,
    limit: int | None = None,
    offset: int | None = None,
    session: AsyncSession = Depends(get_session),
    task_service: TaskServiceProtocol = Depends(get_task_service),
):
    """List tasks filtered by tag.

    Pagination: ``limit`` and ``offset`` are optional. Omit both to fetch
    every matching task in one request — agents and scripts that need the
    full set should leave them unset, or page with ``offset += limit``
    until the response is shorter than ``limit``.
    """
    return await task_service.list_tasks(
        session,
        tag=tag,
        include_descendants=include_descendants,
        limit=limit,
        offset=offset,
    )


# --- Standard task endpoints ---

@router.get("/tasks")
async def list_tasks(
    limit: int | None = None,
    offset: int | None = None,
    session: AsyncSession = Depends(get_session),
    task_service: TaskServiceProtocol = Depends(get_task_service),
):
    """List all non-trashed tasks.

    Pagination: ``limit`` and ``offset`` are optional. Omit both to fetch
    every task in one request (the default for agents and scripts that
    need the full set). To page, increment ``offset`` by ``limit`` until
    the response is shorter than ``limit``.
    """
    return await task_service.list_tasks(session, limit=limit, offset=offset)


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


class ChecklistItemCreate(BaseModel):
    title: str


@router.post("/tasks/{uuid}/checklist", status_code=201)
async def create_checklist_item(
    uuid: str,
    body: ChecklistItemCreate,
    session: AsyncSession = Depends(get_session),
    task_service: TaskServiceProtocol = Depends(get_task_service),
):
    return await task_service.create_checklist_item(session, task_uuid=uuid, title=body.title)


@router.post("/checklist/{uuid}/complete")
async def complete_checklist_item(
    uuid: str,
    session: AsyncSession = Depends(get_session),
    task_service: TaskServiceProtocol = Depends(get_task_service),
):
    return await task_service.complete_checklist_item(session, uuid)


@router.post("/checklist/{uuid}/uncomplete")
async def uncomplete_checklist_item(
    uuid: str,
    session: AsyncSession = Depends(get_session),
    task_service: TaskServiceProtocol = Depends(get_task_service),
):
    return await task_service.uncomplete_checklist_item(session, uuid)


@router.get("/areas")
async def list_areas(
    session: AsyncSession = Depends(get_session),
    task_service: TaskServiceProtocol = Depends(get_task_service),
):
    return await task_service.list_areas(session)


@router.get("/tags")
async def list_tags(
    session: AsyncSession = Depends(get_session),
    tag_service: TagServiceProtocol = Depends(get_tag_service),
):
    return await tag_service.list_tags(session)


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
    contact_uuid: str | None = None
    deadline: float | None = None
    start_date: float | None = None
    start_bucket: int | None = None  # 0=morning (default), 1=evening
    reminder_time: int | None = None
    tags: list[str] | None = None
    auto_create_tags: bool = False


class TaskUpdate(BaseModel):
    title: str | None = None
    notes: str | None = None
    status: int | str | None = None
    schedule: int | str | None = None
    type: int | str | None = None
    area_uuid: str | None = None
    project_uuid: str | None = None
    heading_uuid: str | None = None
    contact_uuid: str | None = None
    deadline: float | None = None
    start_date: float | None = None
    start_bucket: int | None = None
    reminder_time: int | None = None
    tags: list[str] | None = None
    auto_create_tags: bool = False


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


# --- Tag endpoints ---


class TagCreate(BaseModel):
    title: str
    parent: str | None = None
    shortcut: str | None = None


class TagUpdate(BaseModel):
    title: str | None = None
    parent: str | None = None
    shortcut: str | None = None


@router.post("/tags", status_code=201)
async def create_tag(
    body: TagCreate,
    session: AsyncSession = Depends(get_session),
    tag_service: TagServiceProtocol = Depends(get_tag_service),
):
    return await tag_service.create_tag(
        session, title=body.title, parent=body.parent, shortcut=body.shortcut
    )


@router.patch("/tags/{uuid}")
async def update_tag(
    uuid: str,
    body: TagUpdate,
    session: AsyncSession = Depends(get_session),
    tag_service: TagServiceProtocol = Depends(get_tag_service),
):
    kwargs = body.model_dump(exclude_unset=True)
    return await tag_service.update_tag(session, uuid, **kwargs)


@router.delete("/tags/{uuid}", status_code=204)
async def delete_tag(
    uuid: str,
    session: AsyncSession = Depends(get_session),
    tag_service: TagServiceProtocol = Depends(get_tag_service),
):
    await tag_service.delete_tag(session, uuid)
    return Response(status_code=204)
