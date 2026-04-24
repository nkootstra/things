"""API endpoints for Things3 data."""

import time
import uuid as uuid_mod
from datetime import UTC, datetime
from enum import IntEnum

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from things_api.auth import require_api_key
from things_api.db.engine import get_session
from things_api.db.models import Area, ChecklistItem, SyncState, Tag, Task

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


class ChecklistStatus(IntEnum):
    pending = 0
    completed = 3


_STATUS_LABELS = {v: v.name for v in TaskStatus}
_SCHEDULE_LABELS = {v: v.name for v in TaskSchedule}
_TYPE_LABELS = {v: v.name for v in TaskType}
_CHECKLIST_STATUS_LABELS = {v: v.name for v in ChecklistStatus}


def _ts_to_utc(ts: float | None) -> str | None:
    """Convert a Unix timestamp to an ISO 8601 UTC string."""
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=UTC).isoformat()


@router.get("/tasks")
async def list_tasks(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Task).where(Task.trashed == False).order_by(Task.index))
    tasks = result.scalars().all()
    return [_task_to_dict(t) for t in tasks]


@router.get("/tasks/{uuid}")
async def get_task(uuid: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Task).where(Task.uuid == uuid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return _task_to_dict(task)


@router.get("/tasks/{uuid}/checklist")
async def get_task_checklist(uuid: str, session: AsyncSession = Depends(get_session)):
    # Verify task exists
    result = await session.execute(select(Task).where(Task.uuid == uuid))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Task not found")

    result = await session.execute(
        select(ChecklistItem).where(ChecklistItem.task_uuid == uuid).order_by(ChecklistItem.index)
    )
    return [
        {
            "uuid": ci.uuid,
            "title": ci.title,
            "status": _CHECKLIST_STATUS_LABELS.get(ci.status, str(ci.status)),
            "index": ci.index,
            "stop_date": _ts_to_utc(ci.stop_date),
        }
        for ci in result.scalars()
    ]


@router.get("/areas")
async def list_areas(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Area).order_by(Area.index))
    return [{"uuid": a.uuid, "title": a.title, "visible": a.visible, "index": a.index} for a in result.scalars()]


@router.get("/tags")
async def list_tags(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Tag).order_by(Tag.index))
    return [{"uuid": t.uuid, "title": t.title, "shortcut": t.shortcut, "index": t.index} for t in result.scalars()]


@router.get("/sync/status")
async def sync_status(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(SyncState).where(SyncState.id == 1))
    state = result.scalar_one_or_none()
    if not state:
        return {"sync_status": "never", "head_index": 0, "last_sync_at": None, "last_error": None}
    return {
        "sync_status": state.sync_status or "never",
        "head_index": state.head_index,
        "last_sync_at": _ts_to_utc(state.last_sync_at),
        "last_error": state.last_error,
    }


@router.post("/sync")
async def trigger_sync(session: AsyncSession = Depends(get_session)):
    """Manually trigger a full pull + push sync cycle."""
    from things_api.cloud.client import ThingsCloudClient
    from things_api.cloud.sync import pull_sync, push_sync
    from things_api.config import settings as cfg

    if not cfg.things_email or not cfg.things_password:
        raise HTTPException(status_code=503, detail="Things Cloud credentials not configured")

    # Rate limit: check last sync was >60s ago
    result = await session.execute(select(SyncState).where(SyncState.id == 1))
    state = result.scalar_one_or_none()
    if state and state.last_sync_at:
        elapsed = time.time() - state.last_sync_at
        if elapsed < 60:
            raise HTTPException(status_code=429, detail=f"Rate limited. Try again in {int(60 - elapsed)}s")

    client = ThingsCloudClient(email=cfg.things_email, password=cfg.things_password)
    pull_result = await pull_sync(client, session)
    push_result = await push_sync(client, session)

    return {"pull": pull_result, "push": push_result}


def _task_to_dict(t: Task) -> dict:
    return {
        "uuid": t.uuid,
        "title": t.title,
        "notes": t.notes,
        "status": _STATUS_LABELS.get(t.status, str(t.status)),
        "schedule": _SCHEDULE_LABELS.get(t.schedule, str(t.schedule)),
        "type": _TYPE_LABELS.get(t.type, str(t.type)),
        "trashed": t.trashed,
        "index": t.index,
        "today_index": t.today_index,
        "creation_date": _ts_to_utc(t.creation_date),
        "modification_date": _ts_to_utc(t.modification_date),
        "start_date": _ts_to_utc(t.start_date),
        "deadline": _ts_to_utc(t.deadline),
        "completion_date": _ts_to_utc(t.completion_date),
        "area_uuid": t.area_uuid,
        "project_uuid": t.project_uuid,
        "heading_uuid": t.heading_uuid,
    }


# --- Write endpoints ---


def _resolve_enum(value, enum_cls: type[IntEnum]) -> int:
    """Accept int or string name, return the int value."""
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return enum_cls[value].value
        except KeyError:
            valid = ", ".join(e.name for e in enum_cls)
            raise HTTPException(status_code=422, detail=f"Invalid value '{value}'. Valid: {valid}")
    return value


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


@router.post("/tasks", status_code=201)
async def create_task(body: TaskCreate, session: AsyncSession = Depends(get_session)):
    now = time.time()
    task = Task(
        uuid=uuid_mod.uuid4().hex[:24],
        title=body.title,
        notes=body.notes or "",
        status=_resolve_enum(body.status, TaskStatus),
        schedule=_resolve_enum(body.schedule, TaskSchedule),
        type=_resolve_enum(body.type, TaskType),
        area_uuid=body.area_uuid,
        project_uuid=body.project_uuid,
        heading_uuid=body.heading_uuid,
        deadline=body.deadline,
        start_date=body.start_date,
        creation_date=now,
        modification_date=now,
        pending_push=True,
    )
    session.add(task)
    await session.commit()
    return _task_to_dict(task)


@router.patch("/tasks/{uuid}")
async def update_task(uuid: str, body: TaskUpdate, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Task).where(Task.uuid == uuid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    updates = body.model_dump(exclude_unset=True)
    if "status" in updates and updates["status"] is not None:
        updates["status"] = _resolve_enum(updates["status"], TaskStatus)
    if "schedule" in updates and updates["schedule"] is not None:
        updates["schedule"] = _resolve_enum(updates["schedule"], TaskSchedule)
    if "type" in updates and updates["type"] is not None:
        updates["type"] = _resolve_enum(updates["type"], TaskType)

    for field, value in updates.items():
        setattr(task, field, value)
    task.modification_date = time.time()
    task.pending_push = True

    await session.commit()
    return _task_to_dict(task)


@router.delete("/tasks/{uuid}", status_code=204)
async def delete_task(uuid: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Task).where(Task.uuid == uuid))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task.trashed = True
    task.modification_date = time.time()
    task.pending_push = True
    await session.commit()
    return Response(status_code=204)
