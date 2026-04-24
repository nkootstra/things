"""Pull sync logic for Things Cloud."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar
from xml.etree import ElementTree

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from things_api.cloud.schema import (
    ACTION_CREATED,
    ACTION_DELETED,
    ACTION_MODIFIED,
    AreaPayload,
    ChecklistItemPayload,
    TagPayload,
    TaskPayload,
)
import things_api.config as config
from things_api.db.models import Area, ChecklistItem, SyncState, Tag, Task

logger = logging.getLogger(__name__)

T = TypeVar("T")


class SyncCircuitOpenError(Exception):
    def __init__(self, retry_after_seconds: int):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Circuit breaker open. Retry in {retry_after_seconds}s")


async def _with_retry(op_name: str, fn: Callable[[], Awaitable[T]]) -> T:
    attempts = max(1, config.settings.sync_retry_attempts)
    base_delay = max(0.0, config.settings.sync_retry_base_seconds)

    for attempt in range(1, attempts + 1):
        try:
            return await fn()
        except Exception:
            if attempt >= attempts:
                raise
            delay = base_delay * (2 ** (attempt - 1))
            logger.warning("%s failed (attempt %s/%s), retrying in %.2fs", op_name, attempt, attempts, delay)
            await asyncio.sleep(delay)

    raise RuntimeError("unreachable")


def parse_notes(raw_notes: str | dict | None) -> str:
    if not raw_notes:
        return ""
    # Things Cloud sends notes as either XML string or rich text dict
    # Dict format: {'_t': 'tx', 'ch': 0, 'v': '<text>', 't': 1}
    if isinstance(raw_notes, dict):
        return str(raw_notes.get("v", ""))
    try:
        root = ElementTree.fromstring(raw_notes)
        return root.text or ""
    except ElementTree.ParseError:
        return re.sub(r"<[^>]+>", "", raw_notes).strip()


async def _get_or_create_sync_state(session: AsyncSession) -> SyncState:
    result = await session.execute(select(SyncState).where(SyncState.id == 1))
    state = result.scalar_one_or_none()
    if state is None:
        state = SyncState(id=1)
        session.add(state)
        await session.flush()
    return state


def _prepare_circuit_for_attempt(state: SyncState) -> bool:
    """Return True if this attempt is a half-open probe."""
    now = time.time()
    if state.circuit_open_until and state.circuit_open_until > now:
        retry_after = max(1, int(state.circuit_open_until - now))
        raise SyncCircuitOpenError(retry_after)

    if state.circuit_probe_active:
        return True

    if state.sync_status == "circuit_open" and state.circuit_open_until and state.circuit_open_until <= now:
        state.sync_status = "half_open"
        state.circuit_probe_active = True
        return True

    if state.sync_status == "half_open":
        state.circuit_probe_active = True
        return True

    return False


def _record_sync_error(state: SyncState, *, force_open: bool = False) -> None:
    state.sync_errors_total = (state.sync_errors_total or 0) + 1
    state.consecutive_sync_errors = (state.consecutive_sync_errors or 0) + 1

    threshold = max(1, config.settings.sync_circuit_breaker_failures)
    should_open = force_open or bool(state.circuit_probe_active) or state.consecutive_sync_errors >= threshold
    if should_open:
        cooldown = max(1.0, config.settings.sync_circuit_breaker_cooldown_seconds)
        state.circuit_open_until = time.time() + cooldown
        state.sync_status = "circuit_open"
        state.circuit_probe_active = False


def _record_sync_success(state: SyncState, phase: str) -> None:
    if state.circuit_probe_active:
        if phase == "push":
            state.consecutive_sync_errors = 0
            state.circuit_open_until = None
            state.circuit_probe_active = False
            state.sync_status = "synced"
        else:
            # Pull succeeded in half-open mode; keep probe active until push completes.
            state.sync_status = "half_open"
        return

    state.consecutive_sync_errors = 0
    state.circuit_open_until = None


async def _apply_task(session: AsyncSession, uuid: str, action: int, payload: TaskPayload) -> None:
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
    if payload.area_ids and payload.area_ids:
        task.area_uuid = payload.area_ids[0]
    if payload.project_ids and payload.project_ids:
        task.project_uuid = payload.project_ids[0]
    if payload.heading_ids and payload.heading_ids:
        task.heading_uuid = payload.heading_ids[0]


async def _apply_area(session: AsyncSession, uuid: str, action: int, payload: AreaPayload) -> None:
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


async def _apply_tag(session: AsyncSession, uuid: str, action: int, payload: TagPayload) -> None:
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


async def _apply_checklist(session: AsyncSession, uuid: str, action: int, payload: ChecklistItemPayload) -> None:
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


_APPLY_MAP: dict[str, tuple] = {
    "Task6": (TaskPayload, _apply_task),
    "Area2": (AreaPayload, _apply_area),
    "Tag3": (TagPayload, _apply_tag),
    "ChecklistItem3": (ChecklistItemPayload, _apply_checklist),
}


async def pull_sync(client: object, session: AsyncSession) -> dict[str, int]:
    """Pull changes from Things Cloud and apply to local DB."""
    state = await _get_or_create_sync_state(session)
    is_half_open_probe = _prepare_circuit_for_attempt(state)

    if not state.history_key:
        history_key = await client.authenticate()  # type: ignore[attr-defined]
        state.history_key = history_key

    try:
        items, new_index = await _with_retry(
            "pull_sync.get_items",
            lambda: client.get_items(start_index=state.head_index),  # type: ignore[attr-defined]
        )
    except Exception as e:
        state.sync_status = "error"
        state.last_error = str(e)
        _record_sync_error(state, force_open=is_half_open_probe)
        await session.commit()
        raise

    counts: dict[str, int] = {"created": 0, "modified": 0, "deleted": 0, "skipped": 0}

    for item in items:
        for uuid, data in item.items():
            entity_type = data.get("e", "")
            action = data.get("t", 0)
            payload_data = data.get("p", {})

            if entity_type not in _APPLY_MAP:
                counts["skipped"] += 1
                continue

            payload_cls, apply_fn = _APPLY_MAP[entity_type]
            try:
                # Isolate each item so one bad payload does not roll back
                # previously applied valid items in this sync batch.
                async with session.begin_nested():
                    payload = payload_cls.model_validate(payload_data)
                    await apply_fn(session, uuid, action, payload)
            except Exception:
                logger.exception("Failed to apply item %s (type=%s)", uuid, entity_type)
                counts["skipped"] += 1
                continue

            if action == ACTION_CREATED:
                counts["created"] += 1
            elif action == ACTION_MODIFIED:
                counts["modified"] += 1
            elif action == ACTION_DELETED:
                counts["deleted"] += 1

    state.head_index = new_index
    state.last_sync_at = time.time()
    state.sync_status = "synced"
    state.last_error = None
    state.last_pull_skipped = counts["skipped"]
    _record_sync_success(state, phase="pull")

    await session.commit()
    return counts


def _task_to_wire(task: Task) -> dict:
    """Convert a Task to Things Cloud wire format."""
    payload: dict = {}
    if task.title:
        payload["tt"] = task.title
    if task.notes:
        payload["nt"] = f'<note xml:space="preserve">{task.notes}</note>'
    if task.status is not None:
        payload["ss"] = task.status
    if task.schedule is not None:
        payload["st"] = task.schedule
    if task.type is not None:
        payload["tp"] = 1 if task.type == 1 else 0
    if task.trashed is not None:
        payload["tr"] = task.trashed
    if task.index is not None:
        payload["ix"] = task.index
    if task.area_uuid:
        payload["ar"] = [task.area_uuid]
    if task.project_uuid:
        payload["pr"] = [task.project_uuid]
    if task.deadline is not None:
        payload["dd"] = task.deadline
    if task.start_date is not None:
        payload["sr"] = task.start_date
    if task.creation_date is not None:
        payload["cd"] = task.creation_date
    if task.modification_date is not None:
        payload["md"] = task.modification_date

    return {task.uuid: {"t": ACTION_MODIFIED, "e": "Task6", "p": payload}}


async def push_sync(client: object, session: AsyncSession) -> dict[str, int]:
    """Push locally modified tasks to Things Cloud."""
    state = await _get_or_create_sync_state(session)
    is_half_open_probe = _prepare_circuit_for_attempt(state)

    if not state.history_key:
        history_key = await client.authenticate()  # type: ignore[attr-defined]
        state.history_key = history_key

    result = await session.execute(select(Task).where(Task.pending_push == True))
    pending_tasks = result.scalars().all()

    counts: dict[str, int] = {"pushed": 0}

    if not pending_tasks:
        _record_sync_success(state, phase="push")
        await session.commit()
        return counts

    items = [_task_to_wire(t) for t in pending_tasks]

    try:
        new_index = await _with_retry(
            "push_sync.commit",
            lambda: client.commit(items, ancestor_index=state.head_index),  # type: ignore[attr-defined]
        )
    except Exception as e:
        state.sync_status = "push_error"
        state.last_error = str(e)
        _record_sync_error(state, force_open=is_half_open_probe)
        await session.commit()
        raise

    for task in pending_tasks:
        task.pending_push = False

    state.head_index = new_index
    state.last_sync_at = time.time()
    state.sync_status = "synced"
    state.last_error = None
    _record_sync_success(state, phase="push")

    await session.commit()
    counts["pushed"] = len(pending_tasks)
    return counts
