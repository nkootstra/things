"""Pull sync logic for Things Cloud."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar
from xml.etree import ElementTree

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from things_sdk.cloud.handlers import EntityHandlerRegistry, default_registry
from things_sdk.cloud.schema import (
    ACTION_CREATED,
    ACTION_DELETED,
    ACTION_MODIFIED,
)
from things_sdk.protocols import CloudClientProtocol, SyncConfig
from things_sdk.db.models import SyncState, Tag, Task, TaskTag, ChecklistItem

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
    """Parse notes from Things Cloud wire format.

    Things3 sends notes in several formats:
    - Simple text: {"_t": "tx", "ch": 0, "v": "<text>", "t": 1}
    - Rich text with paragraphs: {"_t": "tx", "t": 2, "ps": [{"r": "<text>", ...}]}
    - Clear notes: {"_t": "tx", "t": 0, "diag": "apply"}
    - Legacy XML: '<note xml:space="preserve">text</note>'
    - Plain string
    """
    if not raw_notes:
        return ""
    if isinstance(raw_notes, dict):
        # Check for clear-notes signal
        if raw_notes.get("t") == 0 and raw_notes.get("diag") == "apply":
            return ""
        # Simple text format
        if "v" in raw_notes:
            return str(raw_notes["v"])
        # Rich text with paragraphs
        if "ps" in raw_notes:
            parts = []
            for p in raw_notes["ps"]:
                if isinstance(p, dict) and "r" in p:
                    parts.append(p["r"])
            return "".join(parts)
        return ""
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
    state.last_pull_skipped = counts["skipped"]

    if counts["skipped"] > 0:
        # Skipped items are permanently lost from local state once head_index
        # advances. Treat any skip as a soft error so the operator sees it via
        # /api/sync/status and the circuit breaker eventually trips on chronic
        # skip patterns rather than failing silently.
        logger.error(
            "pull_sync skipped %d items at head_index=%d; investigate handler errors",
            counts["skipped"],
            new_index,
        )
        state.sync_status = "synced_with_skips"
        state.last_error = f"pull_sync skipped {counts['skipped']} items"
        _record_sync_error(state, force_open=is_half_open_probe)
    else:
        state.sync_status = "synced"
        state.last_error = None
        _record_sync_success(state, phase="pull")

    await session.commit()
    return counts


def _to_day_int(ts: float | None) -> int | None:
    """Convert a timestamp to a day-precision integer.

    Things3 sends date-only fields (sr, dd, tir) as integers (epoch seconds
    truncated to midnight). Sending floats crashes Things3.
    """
    if ts is None:
        return None
    return int(ts)


def _task_to_wire(task: Task, tag_uuids: list[str] | None = None) -> list[dict]:
    """Convert a Task to Things Cloud wire format items.

    Returns a list of wire items (usually 1, but 2 when a new task has fields
    that must be applied as a separate update — e.g. deadline, completion_date).

    Things3 merge engine protocol:
    - t=0 (ACTION_CREATED): full payload, but deadline/completion crash if included
    - t=1 (ACTION_MODIFIED): partial payload with only changed fields
    - Fields like dd (deadline) and sp (completion) must be sent as a t=1 update
      AFTER the t=0 create, matching how Things3 itself operates.
    """
    sr_int = _to_day_int(task.start_date)
    dd_int = _to_day_int(task.deadline)
    notes_val: dict = {"_t": "tx", "ch": 0, "v": task.notes or "", "t": 1}

    action = ACTION_CREATED if task.is_new else ACTION_MODIFIED

    payload: dict = {
        "tp": 1 if task.type == 1 else 0,
        "sr": sr_int,
        "dds": None,
        "rt": [],
        "rmd": None,
        "ss": task.status if task.status is not None else 0,
        "tr": task.trashed if task.trashed is not None else False,
        "dl": [],
        "icp": False,
        "st": task.schedule if task.schedule is not None else 0,
        "ar": [task.area_uuid] if task.area_uuid else [],
        "tt": task.title or "",
        "do": 0,
        "lai": None,
        "tir": sr_int,
        "tg": [],  # Tags sent separately for creates (see below)
        "agr": [task.heading_uuid] if task.heading_uuid else [],
        "ix": task.index if task.index is not None else 0,
        "cd": task.creation_date,
        "lt": False,
        "icc": 0,
        "ti": task.today_index if task.today_index is not None else 0,
        "md": task.modification_date,
        "dd": None,  # Deadline sent separately for creates (see below)
        "ato": None,
        "nt": notes_val,
        "icsd": None,
        "pr": [task.project_uuid] if task.project_uuid else [],
        "rp": None,
        "acrd": None,
        "sp": None,  # Completion sent separately for creates (see below)
        "sb": task.start_bucket if task.start_bucket is not None else 0,
        "rr": None,
        "xx": {"sn": {}, "_t": "oo"},
    }

    if task.reminder_time is not None:
        payload["al"] = task.reminder_time

    # For modifications (not creates), include all fields inline
    if action == ACTION_MODIFIED:
        payload["dd"] = dd_int
        payload["sp"] = task.completion_date
        payload["tg"] = tag_uuids if tag_uuids is not None else []

    items = [{task.uuid: {"t": action, "e": "Task6", "p": payload}}]

    # For creates, fields that crash the merge engine must be sent as follow-up updates:
    # dd (deadline), sp (completion), tg (tags)
    if action == ACTION_CREATED:
        update_fields: dict = {}
        if dd_int is not None:
            update_fields["dd"] = dd_int
        if task.completion_date is not None:
            update_fields["sp"] = task.completion_date
        if tag_uuids:
            update_fields["tg"] = tag_uuids
        if update_fields:
            update_fields["md"] = task.modification_date
            items.append({task.uuid: {"t": ACTION_MODIFIED, "e": "Task6", "p": update_fields}})

    return items


def _tag_to_wire(tag: Tag) -> dict:
    """Convert a Tag to Things Cloud wire format.

    Matches the full schema that Things3 sends.
    Uses t=0 for new tags, t=1 for modifications.
    """
    action = ACTION_CREATED if tag.is_new else ACTION_MODIFIED

    payload: dict = {
        "tt": tag.title or "",
        "sh": tag.shortcut,
        "pn": [tag.parent_uuid] if tag.parent_uuid else [],
        "ix": tag.index if tag.index is not None else 0,
        "xx": {"sn": {}, "_t": "oo"},
    }
    return {tag.uuid: {"t": action, "e": "Tag4", "p": payload}}


def _tag_delete_wire(tag_uuid: str) -> dict:
    """Create a deletion wire item for a Tag."""
    return {tag_uuid: {"t": ACTION_DELETED, "e": "Tag4", "p": {}}}


def _checklist_item_to_wire(item: ChecklistItem) -> dict:
    """Convert a ChecklistItem to Things Cloud wire format."""
    action = ACTION_CREATED if item.is_new else ACTION_MODIFIED

    if action == ACTION_CREATED:
        payload: dict = {
            "tt": item.title or "",
            "ss": item.status if item.status is not None else 0,
            "ix": item.index if item.index is not None else 0,
            "sp": item.stop_date,
            "cd": item.creation_date,
            "md": item.modification_date,
            "ts": [item.task_uuid] if item.task_uuid else [],
            "lt": False,
            "xx": {"sn": {}, "_t": "oo"},
        }
    else:
        # Partial update — only changed fields
        payload = {"md": item.modification_date}
        if item.status == 3:
            payload["ss"] = 3
            payload["sp"] = item.stop_date
        elif item.status == 0:
            payload["ss"] = 0
            payload["sp"] = None

    return {item.uuid: {"t": action, "e": "ChecklistItem3", "p": payload}}


async def push_sync(client: CloudClientProtocol, session: AsyncSession) -> dict[str, int]:
    """Push locally modified tags and tasks to Things Cloud.

    Ordering: tag creates/updates first, then tasks, then tag deletes.
    This avoids cloud-side orphan references.
    """
    state = await _get_or_create_sync_state(session)
    is_half_open_probe = _prepare_circuit_for_attempt(state)

    if not state.history_key:
        history_key = await client.authenticate()
        state.history_key = history_key

    # Collect pending tags (creates/updates and deletes separately)
    result = await session.execute(
        select(Tag).where((Tag.pending_push == True) & (Tag.pending_delete == False))
    )
    pending_tags = result.scalars().all()

    result = await session.execute(
        select(Tag).where(Tag.pending_delete == True)
    )
    pending_tag_deletes = result.scalars().all()

    # Collect pending tasks
    result = await session.execute(select(Task).where(Task.pending_push == True))
    pending_tasks = result.scalars().all()

    # Collect pending checklist items
    result = await session.execute(select(ChecklistItem).where(ChecklistItem.pending_push == True))
    pending_checklist_items = result.scalars().all()

    counts: dict[str, int] = {"pushed": 0, "tags_pushed": 0, "tags_deleted": 0, "checklist_pushed": 0}

    if not pending_tasks and not pending_tags and not pending_tag_deletes and not pending_checklist_items:
        _record_sync_success(state, phase="push")
        await session.commit()
        return counts

    # Batch-load tag associations for all pending tasks
    task_tag_map: dict[str, list[str]] = {}
    if pending_tasks:
        task_uuids = [t.uuid for t in pending_tasks]
        tag_result = await session.execute(
            select(TaskTag).where(TaskTag.task_uuid.in_(task_uuids))
        )
        for tt in tag_result.scalars():
            task_tag_map.setdefault(tt.task_uuid, []).append(tt.tag_uuid)

    # Build commit batches. Items sharing a UUID (e.g. create + deadline update)
    # must go in separate commits because JSON doesn't allow duplicate keys.
    # Batch 1: tag creates/updates + task creates (dd/sp stripped)
    # Batch 2: follow-up updates for tasks that needed two-step (deadline, completion)
    # Batch 3: tag deletes
    batch_main: list[dict] = []
    batch_followup: list[dict] = []

    batch_main.extend(_tag_to_wire(t) for t in pending_tags)
    for t in pending_tasks:
        wire_items = _task_to_wire(t, tag_uuids=task_tag_map.get(t.uuid, []))
        batch_main.append(wire_items[0])  # create or full modify
        if len(wire_items) > 1:
            batch_followup.extend(wire_items[1:])  # follow-up updates
    batch_main.extend(_checklist_item_to_wire(ci) for ci in pending_checklist_items)

    batch_tag_deletes: list[dict] = [_tag_delete_wire(t.uuid) for t in pending_tag_deletes]

    # Advance head_index only after BOTH cloud commits succeed AND flag clearing
    # is staged in the same DB transaction. Persisting an advanced head_index in
    # the exception path would cause stale ancestor_index on retry and silent
    # data loss. Use locals; assign to state only on full success.
    pre_push_head_index = state.head_index
    new_main_index = pre_push_head_index
    new_followup_index = pre_push_head_index

    try:
        # Commit main batch
        if batch_main or batch_tag_deletes:
            all_main = batch_main + batch_tag_deletes
            new_main_index = await _with_retry(
                "push_sync.commit",
                lambda: client.commit(all_main, ancestor_index=pre_push_head_index),
            )

        # Commit follow-up batch (deadline/completion updates)
        if batch_followup:
            ancestor = new_main_index
            new_followup_index = await _with_retry(
                "push_sync.commit_followup",
                lambda: client.commit(batch_followup, ancestor_index=ancestor),
            )
        else:
            new_followup_index = new_main_index
    except Exception as e:
        # Do NOT advance head_index or clear pending_push flags. The next pull
        # will catch up any items the cloud accepted; the next push retries
        # the rest with a fresh ancestor_index.
        state.sync_status = "push_error"
        state.last_error = str(e)
        _record_sync_error(state, force_open=is_half_open_probe)
        await session.commit()
        raise

    # Cloud commits succeeded — atomically advance head_index and clear flags.
    state.head_index = new_followup_index

    for tag in pending_tags:
        tag.pending_push = False
        tag.is_new = False

    for tag in pending_tag_deletes:
        await session.execute(delete(TaskTag).where(TaskTag.tag_uuid == tag.uuid))
        await session.delete(tag)

    for task in pending_tasks:
        task.pending_push = False
        task.is_new = False

    for ci in pending_checklist_items:
        ci.pending_push = False
        ci.is_new = False

    state.last_sync_at = time.time()
    state.sync_status = "synced"
    state.last_error = None
    _record_sync_success(state, phase="push")

    await session.commit()
    counts["pushed"] = len(pending_tasks)
    counts["tags_pushed"] = len(pending_tags)
    counts["tags_deleted"] = len(pending_tag_deletes)
    counts["checklist_pushed"] = len(pending_checklist_items)
    return counts
