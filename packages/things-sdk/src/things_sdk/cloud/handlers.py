"""Entity handler strategy pattern for Things Cloud sync items."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from things_sdk.cloud.schema import (
    ACTION_DELETED,
    AreaPayload,
    ChecklistItemPayload,
    TagPayload,
    TaskPayload,
    TombstonePayload,
)
from things_sdk.db.models import Area, ChecklistItem, Tag, Task

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

        if payload.title is not None:
            task.title = payload.title
        if payload.notes is not None:
            task.notes = parse_notes(payload.notes)
        if payload.status is not None:
            task.status = payload.status
        if payload.schedule is not None:
            task.schedule = payload.schedule
        if payload.is_project is not None:
            task.type = 1 if payload.is_project else 0
        if payload.trashed is not None:
            task.trashed = payload.trashed
        if payload.index is not None:
            task.index = payload.index
        if payload.today_index is not None:
            task.today_index = payload.today_index
        if payload.creation_date is not None:
            task.creation_date = payload.creation_date
        if payload.modification_date is not None:
            task.modification_date = payload.modification_date
        if payload.start_date is not None:
            task.start_date = payload.start_date
        if payload.deadline is not None:
            task.deadline = payload.deadline
        if payload.completion_date is not None:
            task.completion_date = payload.completion_date
        if payload.reminder_time is not None:
            task.reminder_time = payload.reminder_time
        if payload.leaves_tombstone is not None:
            task.leaves_tombstone = bool(payload.leaves_tombstone)
        if payload.area_ids and payload.area_ids:
            task.area_uuid = payload.area_ids[0]
        if payload.project_ids and payload.project_ids:
            task.project_uuid = payload.project_ids[0]
        if payload.heading_ids and payload.heading_ids:
            task.heading_uuid = payload.heading_ids[0]
        if payload.contact_ids and payload.contact_ids:
            task.contact_uuid = payload.contact_ids[0]


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
                await session.delete(tag)
            return

        if tag is None:
            tag = Tag(uuid=uuid)
            session.add(tag)

        if payload.title is not None:
            tag.title = payload.title
        if payload.shortcut is not None:
            tag.shortcut = payload.shortcut
        if payload.parent_ids and payload.parent_ids:
            tag.parent_uuid = payload.parent_ids[0]
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

        if payload.title is not None:
            item.title = payload.title
        if payload.status is not None:
            item.status = payload.status
        if payload.index is not None:
            item.index = payload.index
        if payload.stop_date is not None:
            item.stop_date = payload.stop_date
        if task_ref:
            item.task_uuid = task_ref


class TombstoneHandler(EntityHandler):
    """Handle explicit deletion records (Tombstone2) from other Things clients."""

    entity_type = "Tombstone2"
    payload_class = TombstonePayload

    async def apply(self, session: AsyncSession, uuid: str, action: int, payload: TombstonePayload) -> None:
        # A tombstone record means the referenced object was hard-deleted.
        # We look up the entity by uuid and remove it from each table.
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
