"""Tests for pull sync engine — uses real DB, mocked cloud client."""

import time

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from things_api.db.models import Base, SyncState, Task
from things_sdk.cloud.sync import configure as configure_sync


def _reconfigure_sync(settings):
    """Re-push settings into SDK sync module after monkeypatching."""
    configure_sync(settings)


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_sess = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_sess() as s:
        yield s
    await engine.dispose()


class FakeCloudClient:
    """Fake cloud client that returns pre-configured items."""

    def __init__(self, items: list[dict], new_index: int = 1):
        self.items = items
        self.new_index = new_index
        self.history_key = "fake-history-key"

    async def authenticate(self) -> str:
        return self.history_key

    async def get_items(self, start_index: int = 0) -> tuple[list[dict], int]:
        return self.items, self.new_index


class FlakyGetItemsClient(FakeCloudClient):
    def __init__(self, items: list[dict], new_index: int = 1, fail_times: int = 1):
        super().__init__(items, new_index)
        self.fail_times = fail_times
        self.calls = 0

    async def get_items(self, start_index: int = 0) -> tuple[list[dict], int]:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise TimeoutError("transient timeout")
        return self.items, self.new_index


@pytest.mark.asyncio
async def test_pull_sync_creates_task_from_task6(db_session):
    from things_api.cloud.sync import pull_sync

    cloud_items = [
        {"uuid_task_001abcdefghij": {"t": 0, "e": "Task6", "p": {"tt": "Buy milk", "ss": 0, "st": 1}}}
    ]
    client = FakeCloudClient(items=cloud_items, new_index=1)

    counts = await pull_sync(client, db_session)

    assert counts["created"] == 1

    result = await db_session.execute(select(Task).where(Task.uuid == "uuid_task_001abcdefghij"))
    task = result.scalar_one()
    assert task.title == "Buy milk"
    assert task.status == 0
    assert task.schedule == 1


@pytest.mark.asyncio
async def test_pull_sync_deletes_task(db_session):
    from things_api.cloud.sync import pull_sync

    # First create a task
    task = Task(uuid="uuid_del_001abcdefghij", title="To delete")
    db_session.add(task)
    await db_session.commit()

    # Then sync a delete for it
    cloud_items = [
        {"uuid_del_001abcdefghij": {"t": 2, "e": "Task6", "p": {}}}
    ]
    client = FakeCloudClient(items=cloud_items, new_index=2)

    counts = await pull_sync(client, db_session)
    assert counts["deleted"] == 1

    result = await db_session.execute(select(Task).where(Task.uuid == "uuid_del_001abcdefghij"))
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_pull_sync_advances_cursor(db_session):
    from things_api.cloud.sync import pull_sync

    cloud_items = [
        {"uuid_cur_001abcdefghij": {"t": 0, "e": "Task6", "p": {"tt": "Test"}}}
    ]
    client = FakeCloudClient(items=cloud_items, new_index=5)

    await pull_sync(client, db_session)

    result = await db_session.execute(select(SyncState).where(SyncState.id == 1))
    state = result.scalar_one()
    assert state.head_index == 5
    assert state.sync_status == "synced"
    assert state.history_key == "fake-history-key"


@pytest.mark.asyncio
async def test_pull_sync_retries_transient_get_items_error(db_session):
    from things_api.cloud.sync import pull_sync

    cloud_items = [
        {"uuid_retry_pull_abcdefgh": {"t": 0, "e": "Task6", "p": {"tt": "After retry"}}}
    ]
    client = FlakyGetItemsClient(items=cloud_items, new_index=3, fail_times=1)

    counts = await pull_sync(client, db_session)

    assert client.calls == 2
    assert counts["created"] == 1


@pytest.mark.asyncio
async def test_pull_sync_creates_area(db_session):
    from things_api.cloud.sync import pull_sync
    from things_api.db.models import Area

    cloud_items = [
        {"uuid_area_01abcdefghijk": {"t": 0, "e": "Area2", "p": {"tt": "Work", "vs": True}}}
    ]
    client = FakeCloudClient(items=cloud_items, new_index=1)

    counts = await pull_sync(client, db_session)
    assert counts["created"] == 1

    result = await db_session.execute(select(Area).where(Area.uuid == "uuid_area_01abcdefghijk"))
    area = result.scalar_one()
    assert area.title == "Work"


# --- Push sync tests ---


class FakePushClient:
    """Fake client that records commit calls."""

    def __init__(self, history_key: str = "fake-key", head_index: int = 5):
        self.history_key = history_key
        self.committed: list[dict] = []
        self._head_index = head_index

    async def authenticate(self) -> str:
        return self.history_key

    async def commit(self, items: list[dict], ancestor_index: int) -> int:
        self.committed.append({"items": items, "ancestor_index": ancestor_index})
        return self._head_index + len(items)


class FlakyCommitClient(FakePushClient):
    def __init__(self, history_key: str = "fake-key", head_index: int = 5, fail_times: int = 1):
        super().__init__(history_key=history_key, head_index=head_index)
        self.fail_times = fail_times
        self.calls = 0

    async def commit(self, items: list[dict], ancestor_index: int) -> int:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise TimeoutError("transient commit timeout")
        return await super().commit(items, ancestor_index)


@pytest.mark.asyncio
async def test_push_sync_sends_pending_tasks(db_session):
    from things_api.cloud.sync import push_sync

    # Set up sync state
    state = SyncState(id=1, history_key="fake-key", head_index=5)
    db_session.add(state)

    # Create a locally modified task
    task = Task(uuid="push_task_01abcdefghij", title="Push me", pending_push=True, status=0, schedule=1)
    db_session.add(task)
    await db_session.commit()

    client = FakePushClient()
    counts = await push_sync(client, db_session)

    assert counts["pushed"] == 1
    assert len(client.committed) == 1
    assert client.committed[0]["ancestor_index"] == 5

    # Task should no longer be pending
    await db_session.refresh(task)
    assert task.pending_push is False


@pytest.mark.asyncio
async def test_push_sync_skips_when_nothing_pending(db_session):
    from things_api.cloud.sync import push_sync

    state = SyncState(id=1, history_key="fake-key", head_index=5)
    db_session.add(state)
    await db_session.commit()

    client = FakePushClient()
    counts = await push_sync(client, db_session)

    assert counts["pushed"] == 0
    assert len(client.committed) == 0


@pytest.mark.asyncio
async def test_push_sync_retries_transient_commit_error(db_session):
    from things_api.cloud.sync import push_sync

    state = SyncState(id=1, history_key="fake-key", head_index=5)
    db_session.add(state)
    task = Task(uuid="push_retry_abcdefghijk", title="Retry me", pending_push=True)
    db_session.add(task)
    await db_session.commit()

    client = FlakyCommitClient(fail_times=1)
    counts = await push_sync(client, db_session)

    assert client.calls == 2
    assert counts["pushed"] == 1


@pytest.mark.asyncio
async def test_push_sync_failure_during_half_open_reopens_circuit(db_session, monkeypatch):
    from things_api.cloud.sync import push_sync
    from things_api.config import settings

    monkeypatch.setattr(settings, "sync_retry_attempts", 1)
    monkeypatch.setattr(settings, "sync_circuit_breaker_failures", 999)
    monkeypatch.setattr(settings, "sync_circuit_breaker_cooldown_seconds", 30.0)
    _reconfigure_sync(settings)

    db_session.add(
        SyncState(
            id=1,
            history_key="fake-key",
            head_index=5,
            sync_status="half_open",
            circuit_open_until=time.time() - 1,
            consecutive_sync_errors=10,
        )
    )

    db_session.add(Task(uuid="push_half_open_fail_abcdef", title="Retry me", pending_push=True))
    await db_session.commit()

    client = FlakyCommitClient(fail_times=1)
    with pytest.raises(TimeoutError):
        await push_sync(client, db_session)

    result = await db_session.execute(select(SyncState).where(SyncState.id == 1))
    state = result.scalar_one()
    assert state.sync_status == "circuit_open"
    assert state.circuit_open_until is not None
    assert state.circuit_open_until > time.time()


@pytest.mark.asyncio
async def test_pull_sync_handles_dict_notes(db_session):
    """Things Cloud sends notes as rich text dict, not just XML strings."""
    from things_api.cloud.sync import pull_sync

    cloud_items = [
        {"uuid_notes_dict_abcdefgh": {"t": 0, "e": "Task6", "p": {
            "tt": "Dict notes task",
            "nt": {"_t": "tx", "ch": 0, "v": "Hello world", "t": 1},
        }}}
    ]
    client = FakeCloudClient(items=cloud_items, new_index=1)
    counts = await pull_sync(client, db_session)
    assert counts["created"] == 1

    result = await db_session.execute(select(Task).where(Task.uuid == "uuid_notes_dict_abcdefgh"))
    task = result.scalar_one()
    assert task.notes == "Hello world"


@pytest.mark.asyncio
async def test_pull_sync_checklist_modify_without_task_ids(db_session):
    """Modify event for checklist item without ts field should not null out task_uuid."""
    from things_api.cloud.sync import pull_sync
    from things_api.db.models import ChecklistItem

    # First create the checklist item with a task reference
    cloud_items = [
        {"uuid_task_parent_abcdefg": {"t": 0, "e": "Task6", "p": {"tt": "Parent"}}},
        {"uuid_cl_modify_abcdefghi": {"t": 0, "e": "ChecklistItem3", "p": {
            "tt": "Step 1", "ss": 0, "ts": ["uuid_task_parent_abcdefg"],
        }}},
    ]
    client = FakeCloudClient(items=cloud_items, new_index=1)
    await pull_sync(client, db_session)

    # Now modify it without ts field
    cloud_items2 = [
        {"uuid_cl_modify_abcdefghi": {"t": 1, "e": "ChecklistItem3", "p": {
            "tt": "Step 1 updated",
        }}},
    ]
    client2 = FakeCloudClient(items=cloud_items2, new_index=2)
    counts = await pull_sync(client2, db_session)
    assert counts["modified"] == 1

    result = await db_session.execute(select(ChecklistItem).where(ChecklistItem.uuid == "uuid_cl_modify_abcdefghi"))
    item = result.scalar_one()
    assert item.title == "Step 1 updated"
    assert item.task_uuid == "uuid_task_parent_abcdefg"  # NOT nulled out


@pytest.mark.asyncio
async def test_pull_sync_continues_after_item_error(db_session):
    """A failed item should not prevent subsequent items from being applied."""
    from things_api.cloud.sync import pull_sync

    cloud_items = [
        # First: a checklist item with no task ref (will be skipped)
        {"uuid_bad_cl_abcdefghijk": {"t": 0, "e": "ChecklistItem3", "p": {"tt": "Orphan"}}},
        # Second: a valid task (should still succeed)
        {"uuid_good_task_abcdefgh": {"t": 0, "e": "Task6", "p": {"tt": "Good task"}}},
    ]
    client = FakeCloudClient(items=cloud_items, new_index=1)
    counts = await pull_sync(client, db_session)

    # The orphan checklist is silently skipped inside _apply_checklist,
    # but the loop still counts it by action type. Key assertion: the
    # valid task after the skip was still applied successfully.
    result = await db_session.execute(select(Task).where(Task.uuid == "uuid_good_task_abcdefgh"))
    assert result.scalar_one().title == "Good task"


@pytest.mark.asyncio
async def test_pull_sync_item_error_does_not_rollback_previous_valid_item(db_session):
    """If one item fails, earlier applied items in same batch must remain committed."""
    from things_api.cloud.sync import pull_sync

    cloud_items = [
        {"uuid_valid_first_abcdefgh": {"t": 0, "e": "Task6", "p": {"tt": "Keep me"}}},
        # Invalid payload type for title: triggers validation exception
        {"uuid_invalid_second_abcd": {"t": 0, "e": "Task6", "p": {"tt": ["not", "a", "string"]}}},
    ]

    client = FakeCloudClient(items=cloud_items, new_index=2)
    counts = await pull_sync(client, db_session)

    assert counts["created"] == 1
    assert counts["skipped"] == 1

    result = await db_session.execute(select(Task).where(Task.uuid == "uuid_valid_first_abcdefgh"))
    task = result.scalar_one_or_none()
    assert task is not None
    assert task.title == "Keep me"


@pytest.mark.asyncio
async def test_pull_sync_opens_circuit_after_threshold(db_session, monkeypatch):
    from things_api.cloud.sync import pull_sync
    from things_api.config import settings

    monkeypatch.setattr(settings, "sync_retry_attempts", 1)
    monkeypatch.setattr(settings, "sync_circuit_breaker_failures", 1)
    monkeypatch.setattr(settings, "sync_circuit_breaker_cooldown_seconds", 30.0)
    _reconfigure_sync(settings)

    client = FlakyGetItemsClient(items=[], new_index=0, fail_times=1)

    with pytest.raises(TimeoutError):
        await pull_sync(client, db_session)

    result = await db_session.execute(select(SyncState).where(SyncState.id == 1))
    state = result.scalar_one()
    assert state.sync_status == "circuit_open"
    assert (state.consecutive_sync_errors or 0) == 1
    assert state.circuit_open_until is not None
    assert state.circuit_open_until > time.time()


@pytest.mark.asyncio
async def test_pull_sync_short_circuits_when_circuit_is_open(db_session):
    from things_api.cloud.sync import SyncCircuitOpenError, pull_sync

    db_session.add(
        SyncState(
            id=1,
            history_key="fake-history-key",
            sync_status="circuit_open",
            circuit_open_until=time.time() + 30,
        )
    )
    await db_session.commit()

    client = FlakyGetItemsClient(items=[], new_index=0, fail_times=0)

    with pytest.raises(SyncCircuitOpenError):
        await pull_sync(client, db_session)

    assert client.calls == 0


@pytest.mark.asyncio
async def test_half_open_probe_failure_reopens_immediately(db_session, monkeypatch):
    from things_api.cloud.sync import pull_sync
    from things_api.config import settings

    monkeypatch.setattr(settings, "sync_retry_attempts", 1)
    monkeypatch.setattr(settings, "sync_circuit_breaker_failures", 999)
    monkeypatch.setattr(settings, "sync_circuit_breaker_cooldown_seconds", 30.0)
    _reconfigure_sync(settings)

    db_session.add(
        SyncState(
            id=1,
            history_key="fake-history-key",
            sync_status="circuit_open",
            circuit_open_until=time.time() - 1,
            consecutive_sync_errors=10,
        )
    )
    await db_session.commit()

    client = FlakyGetItemsClient(items=[], new_index=0, fail_times=1)

    with pytest.raises(TimeoutError):
        await pull_sync(client, db_session)

    result = await db_session.execute(select(SyncState).where(SyncState.id == 1))
    state = result.scalar_one()
    assert state.sync_status == "circuit_open"
    assert state.circuit_open_until is not None
    assert state.circuit_open_until > time.time()


@pytest.mark.asyncio
async def test_half_open_probe_success_closes_circuit(db_session):
    from things_api.cloud.sync import pull_sync, push_sync

    db_session.add(
        SyncState(
            id=1,
            history_key="fake-history-key",
            sync_status="circuit_open",
            circuit_open_until=time.time() - 1,
            consecutive_sync_errors=4,
        )
    )
    await db_session.commit()

    pull_client = FakeCloudClient(
        items=[{"uuid_half_open_ok_abcdef": {"t": 0, "e": "Task6", "p": {"tt": "Recovered"}}}],
        new_index=10,
    )

    counts = await pull_sync(pull_client, db_session)
    assert counts["created"] == 1

    # Pull success in half-open keeps probe active until push completes.
    push_client = FakePushClient(history_key="fake-history-key", head_index=10)
    push_counts = await push_sync(push_client, db_session)
    assert push_counts["pushed"] == 0

    result = await db_session.execute(select(SyncState).where(SyncState.id == 1))
    state = result.scalar_one()
    assert state.sync_status == "synced"
    assert (state.consecutive_sync_errors or 0) == 0
    assert state.circuit_open_until is None
