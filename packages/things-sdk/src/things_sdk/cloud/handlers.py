"""Entity handler strategy pattern for Things Cloud sync items."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from things_sdk.cloud.schema import (
    ACTION_DELETED,
    AreaPayload,
    ChecklistItemPayload,
    TagPayload,
    TaskPayload,
    TombstonePayload,
)
from things_sdk.db.models import Area, ChecklistItem, Tag, Task, TaskTag

logger = logging.getLogger(__name__)


class EntityHandler(ABC):
    """Base class for entity-specific sync handlers."""

    entity_type: str
    payload_class: type[BaseModel]

    @abstractmethod
    async def apply(self, session: AsyncSession, uuid: str, action: int, payload: Any) -> None:
        ...


class TaskHandler(EntityHandler):
    entity_type = "Task6"
    payload_class = TaskPayload

    async def apply(self, session: AsyncSession, uuid: str, action: int, payload: TaskPayload) -> None:
        from things_sdk.cloud.sync import parse_notes

        result = await session.execute(select(Task).where(Task.uuid == uuid))
        task = result.scalar_one_or_none()

        if action == ACTION_DELETED:
            if task:
                await session.delete(task)
            return

        if task is None:
            task = Task(uuid=uuid)
            session.add(task)

        # Use model_fields_set to distinguish "not sent" from "sent as null".
        # A partial update like {"sp": null} explicitly clears completion_date.
        sent = payload.model_fields_set

        if "title" in sent:
            task.title = payload.title or ""
        if "notes" in sent:
            task.notes = parse_notes(payload.notes)
        if "status" in sent and payload.status is not None:
            task.status = payload.status
        if "schedule" in sent and payload.schedule is not None:
            task.schedule = payload.schedule
        if "is_project" in sent and payload.is_project is not None:
            task.type = 1 if payload.is_project else 0
        if "trashed" in sent and payload.trashed is not None:
            task.trashed = payload.trashed
        if "index" in sent and payload.index is not None:
            task.index = payload.index
        if "today_index" in sent and payload.today_index is not None:
            task.today_index = payload.today_index
        if "start_bucket" in sent:
            task.start_bucket = payload.start_bucket or 0
        if "creation_date" in sent:
            task.creation_date = payload.creation_date
        if "modification_date" in sent:
            task.modification_date = payload.modification_date
        if "start_date" in sent:
            task.start_date = payload.start_date  # can be None (clear)
        if "deadline" in sent:
            task.deadline = payload.deadline  # can be None (clear)
        if "completion_date" in sent:
            task.completion_date = payload.completion_date  # can be None (uncomplete)
        if "reminder_time" in sent:
            task.reminder_time = payload.reminder_time
        if "leaves_tombstone" in sent:
            task.leaves_tombstone = bool(payload.leaves_tombstone) if payload.leaves_tombstone is not None else False
        # Containment fields: cloud sends [] to clear the relationship.
        # Use model_fields_set to distinguish "not sent" from "sent as []".
        if "area_ids" in sent:
            task.area_uuid = payload.area_ids[0] if payload.area_ids else None
        if "project_ids" in sent:
            task.project_uuid = payload.project_ids[0] if payload.project_ids else None
        if "heading_ids" in sent:
            task.heading_uuid = payload.heading_ids[0] if payload.heading_ids else None
        if "contact_ids" in sent:
            if isinstance(payload.contact_ids, list):
                task.contact_uuid = payload.contact_ids[0] if payload.contact_ids else None
            # int value (0) means no contact — ignore

        # Replace-set tag associations (cloud is source of truth)
        if payload.tag_ids is not None:
            await session.execute(
                delete(TaskTag).where(TaskTag.task_uuid == uuid)
            )
            for tag_uuid in payload.tag_ids:
                session.add(TaskTag(task_uuid=uuid, tag_uuid=tag_uuid))


class AreaHandler(EntityHandler):
    entity_type = "Area3"
    payload_class = AreaPayload

    async def apply(self, session: AsyncSession, uuid: str, action: int, payload: AreaPayload) -> None:
        result = await session.execute(select(Area).where(Area.uuid == uuid))
        area = result.scalar_one_or_none()

        if action == ACTION_DELETED:
            if area:
                await session.delete(area)
            return

        if area is None:
            area = Area(uuid=uuid)
            session.add(area)

        if payload.title is not None:
            area.title = payload.title
        if payload.visible is not None:
            area.visible = payload.visible
        if payload.index is not None:
            area.index = payload.index


class TagHandler(EntityHandler):
    entity_type = "Tag4"
    payload_class = TagPayload

    async def apply(self, session: AsyncSession, uuid: str, action: int, payload: TagPayload) -> None:
        result = await session.execute(select(Tag).where(Tag.uuid == uuid))
        tag = result.scalar_one_or_none()

        if action == ACTION_DELETED:
            if tag:
                await session.execute(delete(TaskTag).where(TaskTag.tag_uuid == uuid))
                await session.delete(tag)
            return

        if tag is None:
            tag = Tag(uuid=uuid)
            session.add(tag)

        sent = payload.model_fields_set
        if payload.title is not None:
            tag.title = payload.title
        if payload.shortcut is not None:
            tag.shortcut = payload.shortcut
        # Cloud sends parent_ids=[] to move a tag back to root.
        if "parent_ids" in sent:
            tag.parent_uuid = payload.parent_ids[0] if payload.parent_ids else None
        if payload.index is not None:
            tag.index = payload.index


class ChecklistItemHandler(EntityHandler):
    entity_type = "ChecklistItem3"
    payload_class = ChecklistItemPayload

    async def apply(self, session: AsyncSession, uuid: str, action: int, payload: ChecklistItemPayload) -> None:
        result = await session.execute(select(ChecklistItem).where(ChecklistItem.uuid == uuid))
        item = result.scalar_one_or_none()

        if action == ACTION_DELETED:
            if item:
                await session.delete(item)
            return

        task_ref = payload.task_ids[0] if payload.task_ids and payload.task_ids[0] else None

        if item is None:
            if not task_ref:
                logger.warning("ChecklistItem %s has no task reference, skipping create", uuid)
                return
            item = ChecklistItem(uuid=uuid, task_uuid=task_ref)
            session.add(item)

        sent = payload.model_fields_set
        if "title" in sent:
            item.title = payload.title or ""
        if "status" in sent and payload.status is not None:
            item.status = payload.status
        if "index" in sent and payload.index is not None:
            item.index = payload.index
        if "stop_date" in sent:
            item.stop_date = payload.stop_date  # can be None (uncomplete)
        if task_ref:
            item.task_uuid = task_ref


class TombstoneHandler(EntityHandler):
    """Handle explicit deletion records (Tombstone2) from other Things clients."""

    entity_type = "Tombstone2"
    payload_class = TombstonePayload

    async def apply(self, session: AsyncSession, uuid: str, action: int, payload: TombstonePayload) -> None:
        # A tombstone record means the referenced object was hard-deleted.
        # We look up the entity by uuid and remove it from each table.
        # Clean up TaskTag associations if it's a task or tag.
        await session.execute(delete(TaskTag).where(TaskTag.task_uuid == uuid))
        await session.execute(delete(TaskTag).where(TaskTag.tag_uuid == uuid))

        for model_cls in (Task, Area, Tag, ChecklistItem):
            result = await session.execute(
                select(model_cls).where(model_cls.uuid == uuid)  # type: ignore[attr-defined]
            )
            obj = result.scalar_one_or_none()
            if obj is not None:
                await session.delete(obj)
                return


# --- Registry ---

_DEFAULT_HANDLERS: list[EntityHandler] = [
    TaskHandler(),
    AreaHandler(),
    TagHandler(),
    ChecklistItemHandler(),
    TombstoneHandler(),
]


class EntityHandlerRegistry:
    def __init__(self, handlers: list[EntityHandler] | None = None) -> None:
        self._map: dict[str, EntityHandler] = {}
        for h in (handlers or _DEFAULT_HANDLERS):
            self.register(h)

    def register(self, handler: EntityHandler) -> None:
        self._map[handler.entity_type] = handler

    def get(self, entity_type: str) -> EntityHandler | None:
        return self._map.get(entity_type)

    @property
    def supported_types(self) -> set[str]:
        return set(self._map.keys())


# Module-level default registry
default_registry = EntityHandlerRegistry()
