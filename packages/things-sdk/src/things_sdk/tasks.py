"""Task/area/tag application service."""

from __future__ import annotations

import time
import uuid as uuid_mod
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from things_sdk.db.models import Area, ChecklistItem, Tag, Task, TaskTag
from things_sdk.errors import EntityNotFoundError
_STATUS_LABELS = {0: "pending", 2: "cancelled", 3: "completed"}
_SCHEDULE_LABELS = {0: "inbox", 1: "anytime", 2: "someday"}
_TYPE_LABELS = {0: "task", 1: "project", 2: "heading"}
_CHECKLIST_STATUS_LABELS = {0: "pending", 3: "completed"}


def _start_of_today_epoch() -> float:
    """Return Unix timestamp for start of today (00:00:00 UTC)."""
    now = datetime.now(tz=UTC)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.timestamp()


def _paginate(query: Select, limit: int | None, offset: int | None) -> Select:
    """Apply optional limit/offset pagination to a query."""
    if offset is not None:
        query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)
    return query


class TaskService:
    async def list_tasks(
        self,
        session: AsyncSession,
        *,
        tag: str | None = None,
        include_descendants: bool = True,
    ) -> list[dict]:
        query = select(Task).where(Task.trashed == False).order_by(Task.index)

        if tag is not None:
            tag_uuids = await self._resolve_tag_filter(session, tag, include_descendants)
            query = query.where(
                Task.uuid.in_(
                    select(TaskTag.task_uuid).where(TaskTag.tag_uuid.in_(tag_uuids))
                )
            )

        result = await session.execute(query)
        tasks = result.scalars().all()
        return [await self._task_to_dict(session, t) for t in tasks]

    # --- Smart lists ---

    async def list_inbox(
        self, session: AsyncSession, *, limit: int | None = None, offset: int | None = None
    ) -> list[dict]:
        query = (
            select(Task)
            .where(Task.schedule == 0, Task.status == 0, Task.trashed == False, Task.type == 0)
            .order_by(Task.index)
        )
        result = await session.execute(_paginate(query, limit, offset))
        return [await self._task_to_dict(session, t) for t in result.scalars()]

    async def list_today(
        self, session: AsyncSession, *, limit: int | None = None, offset: int | None = None
    ) -> list[dict]:
        today = _start_of_today_epoch()
        query = (
            select(Task)
            .where(
                Task.status == 0,
                Task.trashed == False,
                Task.start_date.isnot(None),
                Task.start_date <= today + 86399,  # end of today
            )
            .order_by(Task.today_index, Task.index)
        )
        result = await session.execute(_paginate(query, limit, offset))
        return [await self._task_to_dict(session, t) for t in result.scalars()]

    async def list_upcoming(
        self, session: AsyncSession, *, limit: int | None = None, offset: int | None = None
    ) -> list[dict]:
        today_end = _start_of_today_epoch() + 86399
        query = (
            select(Task)
            .where(
                Task.status == 0,
                Task.trashed == False,
                Task.start_date.isnot(None),
                Task.start_date > today_end,
            )
            .order_by(Task.start_date, Task.deadline)
        )
        result = await session.execute(_paginate(query, limit, offset))
        return [await self._task_to_dict(session, t) for t in result.scalars()]

    async def list_anytime(
        self, session: AsyncSession, *, limit: int | None = None, offset: int | None = None
    ) -> list[dict]:
        query = (
            select(Task)
            .where(Task.schedule == 1, Task.status == 0, Task.trashed == False)
            .order_by(Task.index)
        )
        result = await session.execute(_paginate(query, limit, offset))
        return [await self._task_to_dict(session, t) for t in result.scalars()]

    async def list_someday(
        self, session: AsyncSession, *, limit: int | None = None, offset: int | None = None
    ) -> list[dict]:
        query = (
            select(Task)
            .where(Task.schedule == 2, Task.status == 0, Task.trashed == False)
            .order_by(Task.index)
        )
        result = await session.execute(_paginate(query, limit, offset))
        return [await self._task_to_dict(session, t) for t in result.scalars()]

    async def list_logbook(
        self,
        session: AsyncSession,
        *,
        since: float | None = None,
        limit: int | None = 100,
        offset: int | None = None,
    ) -> list[dict]:
        if since is None:
            since = (datetime.now(tz=UTC) - timedelta(days=30)).timestamp()
        query = (
            select(Task)
            .where(
                Task.status == 3,
                Task.trashed == False,
                Task.completion_date.isnot(None),
                Task.completion_date >= since,
            )
            .order_by(Task.completion_date.desc())
        )
        result = await session.execute(_paginate(query, limit, offset))
        return [await self._task_to_dict(session, t) for t in result.scalars()]

    async def list_trash(
        self, session: AsyncSession, *, limit: int | None = 100, offset: int | None = None
    ) -> list[dict]:
        query = (
            select(Task)
            .where(Task.trashed == True)
            .order_by(Task.modification_date.desc())
        )
        result = await session.execute(_paginate(query, limit, offset))
        return [await self._task_to_dict(session, t) for t in result.scalars()]

    async def get_task(self, session: AsyncSession, uuid: str) -> dict:
        result = await session.execute(select(Task).where(Task.uuid == uuid))
        task = result.scalar_one_or_none()
        if not task:
            raise EntityNotFoundError("Task", uuid)
        return await self._task_to_dict(session, task)

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
        contact_uuid: str | None = None,
        deadline: float | None,
        start_date: float | None,
        reminder_time: int | None = None,
        tags: list[str] | None = None,
        auto_create_tags: bool = False,
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
            contact_uuid=contact_uuid,
            deadline=deadline,
            start_date=start_date,
            reminder_time=reminder_time,
            creation_date=now,
            modification_date=now,
            pending_push=True,
        )
        session.add(task)
        await session.flush()

        if tags is not None:
            await self._set_task_tags(session, task.uuid, tags, auto_create_tags)

        await session.commit()
        return await self._task_to_dict(session, task)

    async def update_task(self, session: AsyncSession, uuid: str, updates: dict) -> dict:
        result = await session.execute(select(Task).where(Task.uuid == uuid))
        task = result.scalar_one_or_none()
        if not task:
            raise EntityNotFoundError("Task", uuid)

        # Extract tag-related updates
        tag_list = updates.pop("tags", None)
        auto_create = updates.pop("auto_create_tags", False)

        for field, value in updates.items():
            setattr(task, field, value)
        task.modification_date = time.time()
        task.pending_push = True

        if tag_list is not None:
            await self._set_task_tags(session, uuid, tag_list, auto_create)

        await session.commit()
        return await self._task_to_dict(session, task)

    async def delete_task(self, session: AsyncSession, uuid: str) -> None:
        result = await session.execute(select(Task).where(Task.uuid == uuid))
        task = result.scalar_one_or_none()
        if not task:
            raise EntityNotFoundError("Task", uuid)

        task.trashed = True
        task.modification_date = time.time()
        task.pending_push = True
        await session.commit()

    # --- Tag helpers ---

    async def _resolve_tag_filter(
        self, session: AsyncSession, tag: str, include_descendants: bool
    ) -> list[str]:
        """Resolve a tag name/UUID to a list of tag UUIDs for filtering."""
        from things_sdk.tags import TagService
        tag_svc = TagService()
        resolved = await tag_svc.resolve_tag(session, tag)
        tag_uuids = [resolved["uuid"]]
        if include_descendants:
            descendants = await tag_svc.get_descendants(session, resolved["uuid"])
            tag_uuids.extend(descendants)
        return tag_uuids

    async def _set_task_tags(
        self, session: AsyncSession, task_uuid: str, tags: list[str], auto_create: bool
    ) -> None:
        """Replace-set tags on a task. Resolves names/UUIDs."""
        from things_sdk.tags import TagService
        from sqlalchemy import delete as sa_delete
        tag_svc = TagService()

        tag_uuids: list[str] = []
        for tag_ref in tags:
            try:
                resolved = await tag_svc.resolve_tag(session, tag_ref)
                tag_uuids.append(resolved["uuid"])
            except EntityNotFoundError:
                if auto_create:
                    parts = tag_ref.split("/")
                    parent_uuid: str | None = None
                    last_uuid = ""
                    for part in parts:
                        # Try to find existing tag at this level
                        from things_sdk.db.models import Tag as TagModel
                        result = await session.execute(
                            select(TagModel).where(
                                TagModel.title == part,
                                TagModel.parent_uuid == parent_uuid,
                            )
                        )
                        existing = result.scalar_one_or_none()
                        if existing:
                            parent_uuid = existing.uuid
                            last_uuid = existing.uuid
                        else:
                            created = await tag_svc.create_tag(
                                session, title=part, parent=parent_uuid
                            )
                            parent_uuid = created["uuid"]
                            last_uuid = created["uuid"]
                    tag_uuids.append(last_uuid)
                else:
                    raise

        # Replace-set: delete existing, insert new
        from sqlalchemy import delete as sa_delete2
        await session.execute(sa_delete2(TaskTag).where(TaskTag.task_uuid == task_uuid))
        for tag_uuid in tag_uuids:
            session.add(TaskTag(task_uuid=task_uuid, tag_uuid=tag_uuid))
        await session.flush()

    async def _get_task_tags(self, session: AsyncSession, task_uuid: str) -> list[dict]:
        """Get tags for a task as [{uuid, title}]."""
        result = await session.execute(
            select(Tag)
            .where(
                Tag.uuid.in_(
                    select(TaskTag.tag_uuid).where(TaskTag.task_uuid == task_uuid)
                )
            )
            .order_by(Tag.index)
        )
        return [{"uuid": t.uuid, "title": t.title} for t in result.scalars()]

    async def _task_to_dict(self, session: AsyncSession, t: Task) -> dict:
        tags = await self._get_task_tags(session, t.uuid)
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
            "contact_uuid": t.contact_uuid,
            "tags": tags,
        }


def _ts_to_utc(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=UTC).isoformat()
