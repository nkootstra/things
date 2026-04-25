"""Task/area/tag application service."""

from __future__ import annotations

import time
import uuid as uuid_mod
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from things_sdk.db.models import Area, ChecklistItem, Tag, Task
from things_sdk.errors import EntityNotFoundError
_STATUS_LABELS = {0: "pending", 2: "cancelled", 3: "completed"}
_SCHEDULE_LABELS = {0: "inbox", 1: "anytime", 2: "someday"}
_TYPE_LABELS = {0: "task", 1: "project", 2: "heading"}
_CHECKLIST_STATUS_LABELS = {0: "pending", 3: "completed"}


class TaskService:
    async def list_tasks(self, session: AsyncSession) -> list[dict]:
        result = await session.execute(select(Task).where(Task.trashed == False).order_by(Task.index))
        tasks = result.scalars().all()
        return [self._task_to_dict(t) for t in tasks]

    async def get_task(self, session: AsyncSession, uuid: str) -> dict:
        result = await session.execute(select(Task).where(Task.uuid == uuid))
        task = result.scalar_one_or_none()
        if not task:
            raise EntityNotFoundError("Task", uuid)
        return self._task_to_dict(task)

    async def get_task_checklist(self, session: AsyncSession, uuid: str) -> list[dict]:
        result = await session.execute(select(Task).where(Task.uuid == uuid))
        if not result.scalar_one_or_none():
            raise EntityNotFoundError("Task", uuid)

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

    async def list_areas(self, session: AsyncSession) -> list[dict]:
        result = await session.execute(select(Area).order_by(Area.index))
        return [{"uuid": a.uuid, "title": a.title, "visible": a.visible, "index": a.index} for a in result.scalars()]

    async def list_tags(self, session: AsyncSession) -> list[dict]:
        result = await session.execute(select(Tag).order_by(Tag.index))
        return [{"uuid": t.uuid, "title": t.title, "shortcut": t.shortcut, "index": t.index} for t in result.scalars()]

    async def create_task(
        self,
        session: AsyncSession,
        *,
        title: str,
        notes: str | None,
        status: int,
        schedule: int,
        type: int,
        area_uuid: str | None,
        project_uuid: str | None,
        heading_uuid: str | None,
        deadline: float | None,
        start_date: float | None,
    ) -> dict:
        now = time.time()
        task = Task(
            uuid=uuid_mod.uuid4().hex[:22],
            title=title,
            notes=notes or "",
            status=status,
            schedule=schedule,
            type=type,
            area_uuid=area_uuid,
            project_uuid=project_uuid,
            heading_uuid=heading_uuid,
            deadline=deadline,
            start_date=start_date,
            creation_date=now,
            modification_date=now,
            pending_push=True,
        )
        session.add(task)
        await session.commit()
        return self._task_to_dict(task)

    async def update_task(self, session: AsyncSession, uuid: str, updates: dict) -> dict:
        result = await session.execute(select(Task).where(Task.uuid == uuid))
        task = result.scalar_one_or_none()
        if not task:
            raise EntityNotFoundError("Task", uuid)

        for field, value in updates.items():
            setattr(task, field, value)
        task.modification_date = time.time()
        task.pending_push = True

        await session.commit()
        return self._task_to_dict(task)

    async def delete_task(self, session: AsyncSession, uuid: str) -> None:
        result = await session.execute(select(Task).where(Task.uuid == uuid))
        task = result.scalar_one_or_none()
        if not task:
            raise EntityNotFoundError("Task", uuid)

        task.trashed = True
        task.modification_date = time.time()
        task.pending_push = True
        await session.commit()

    def _task_to_dict(self, t: Task) -> dict:
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
            "reminder_time": t.reminder_time,
            "area_uuid": t.area_uuid,
            "project_uuid": t.project_uuid,
            "heading_uuid": t.heading_uuid,
        }


def _ts_to_utc(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=UTC).isoformat()
