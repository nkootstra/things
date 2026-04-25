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

from things_sdk.cloud.handlers import EntityHandlerRegistry, default_registry
from things_sdk.cloud.schema import (
    ACTION_CREATED,
    ACTION_DELETED,
    ACTION_MODIFIED,
)
from things_sdk.protocols import CloudClientProtocol, SyncConfig
from things_sdk.db.models import SyncState, Task

logger = logging.getLogger(__name__)

T = TypeVar("T")

_config: SyncConfig | None = None


def configure(sync_config: SyncConfig) -> None:
    global _config
    _config = sync_config


def _get_config() -> SyncConfig:
    if _config is None:
        raise RuntimeError("things_sdk.cloud.sync not configured. Call configure() first.")
    return _config


class SyncCircuitOpenError(Exception):
    def __init__(self, retry_after_seconds: int):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Circuit breaker open. Retry in {retry_after_seconds}s")


async def _with_retry(op_name: str, fn: Callable[[], Awaitable[T]]) -> T:
    cfg = _get_config()
    attempts = max(1, cfg.sync_retry_attempts)
    base_delay = max(0.0, cfg.sync_retry_base_seconds)

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

    cfg = _get_config()
    threshold = max(1, cfg.sync_circuit_breaker_failures)
    should_open = force_open or bool(state.circuit_probe_active) or state.consecutive_sync_errors >= threshold
    if should_open:
        cooldown = max(1.0, _get_config().sync_circuit_breaker_cooldown_seconds)
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


async def pull_sync(
    client: CloudClientProtocol,
    session: AsyncSession,
    *,
    registry: EntityHandlerRegistry | None = None,
) -> dict[str, int]:
    """Pull changes from Things Cloud and apply to local DB."""
    state = await _get_or_create_sync_state(session)
    is_half_open_probe = _prepare_circuit_for_attempt(state)

    if not state.history_key:
        history_key = await client.authenticate()
        state.history_key = history_key

    try:
        items, new_index = await _with_retry(
            "pull_sync.get_items",
            lambda: client.get_items(start_index=state.head_index),
        )
    except Exception as e:
        state.sync_status = "error"
        state.last_error = str(e)
        _record_sync_error(state, force_open=is_half_open_probe)
        await session.commit()
        raise

    counts: dict[str, int] = {"created": 0, "modified": 0, "deleted": 0, "skipped": 0}
    _registry = registry or default_registry

    for item in items:
        for uuid, data in item.items():
            entity_type = data.get("e", "")
            action = data.get("t", 0)
            payload_data = data.get("p", {})

            handler = _registry.get(entity_type)
            if handler is None:
                counts["skipped"] += 1
                continue

            try:
                async with session.begin_nested():
                    payload = handler.payload_class.model_validate(payload_data)
                    await handler.apply(session, uuid, action, payload)
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
    if task.reminder_time is not None:
        payload["al"] = task.reminder_time

    return {task.uuid: {"t": ACTION_MODIFIED, "e": "Task6", "p": payload}}


async def push_sync(client: CloudClientProtocol, session: AsyncSession) -> dict[str, int]:
    """Push locally modified tasks to Things Cloud."""
    state = await _get_or_create_sync_state(session)
    is_half_open_probe = _prepare_circuit_for_attempt(state)

    if not state.history_key:
        history_key = await client.authenticate()
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
            lambda: client.commit(items, ancestor_index=state.head_index),
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
