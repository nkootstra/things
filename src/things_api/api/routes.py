"""Read-only API endpoints for Things3 data."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from things_api.auth import require_api_key
from things_api.db.engine import get_session
from things_api.db.models import Area, SyncState, Tag, Task

router = APIRouter(prefix="/api", dependencies=[Depends(require_api_key)])


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
        "last_sync_at": state.last_sync_at,
        "last_error": state.last_error,
    }


def _task_to_dict(t: Task) -> dict:
    return {
        "uuid": t.uuid,
        "title": t.title,
        "notes": t.notes,
        "status": t.status,
        "schedule": t.schedule,
        "type": t.type,
        "trashed": t.trashed,
        "index": t.index,
        "today_index": t.today_index,
        "creation_date": t.creation_date,
        "modification_date": t.modification_date,
        "start_date": t.start_date,
        "deadline": t.deadline,
        "completion_date": t.completion_date,
        "area_uuid": t.area_uuid,
        "project_uuid": t.project_uuid,
        "heading_uuid": t.heading_uuid,
    }
