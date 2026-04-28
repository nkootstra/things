"""SDK-only tests — no FastAPI, no HTTP layer."""

import time

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from things_sdk import (
    Area,
    Base,
    ChecklistItem,
    CloudClientProtocol,
    EntityNotFoundError,
    SyncCircuitOpenError,
    SyncState,
    Tag,
    Task,
    TaskService,
    ThingsClient,
    ThingsCloudAuthError,
    configure_sync,
    create_engine_and_session,
    init_db,
    parse_notes,
    pull_sync,
    push_sync,
)


# --- Fixtures ---


class _DefaultSyncConfig:
    sync_retry_attempts = 3
    sync_retry_base_seconds = 0.0
    sync_circuit_breaker_failures = 3
    sync_circuit_breaker_cooldown_seconds = 60.0


@pytest.fixture(autouse=True)
def _configure_sdk_sync():
    configure_sync(_DefaultSyncConfig())


@pytest.fixture
async def sdk_session():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


class FakeCloudClient:
    def __init__(self, items=None, new_index=1):
        self.items = items or []
        self.new_index = new_index
        self.history_key = "fake-key"
        self.committed = []
        self.closed = False

    async def authenticate(self) -> str:
        return self.history_key

    async def get_items(self, start_index: int = 0) -> tuple[list[dict], int]:
        return self.items, self.new_index

    async def commit(self, items: list[dict], ancestor_index: int) -> int:
        self.committed.append(items)
        return self.new_index + len(items)

    async def close(self) -> None:
        self.closed = True


# --- Top-level import tests ---


def test_sdk_top_level_imports():
    """All public names should be importable from things_sdk."""
    assert ThingsClient is not None
    assert TaskService is not None
    assert CloudClientProtocol is not None
    assert Task is not None
    assert Area is not None
    assert Tag is not None
    assert SyncState is not None
    assert Base is not None


# --- Model tests ---


@pytest.mark.asyncio
async def test_create_task_model(sdk_session):
    task = Task(uuid="sdk_test_task_abcdefgh", title="SDK task", status=0, schedule=1)
    sdk_session.add(task)
    await sdk_session.commit()

    result = await sdk_session.execute(select(Task).where(Task.uuid == "sdk_test_task_abcdefgh"))
    loaded = result.scalar_one()
    assert loaded.title == "SDK task"


@pytest.mark.asyncio
async def test_create_area_model(sdk_session):
    area = Area(uuid="sdk_test_area_abcdefgh", title="SDK area")
    sdk_session.add(area)
    await sdk_session.commit()

    result = await sdk_session.execute(select(Area).where(Area.uuid == "sdk_test_area_abcdefgh"))
    assert result.scalar_one().title == "SDK area"


# --- Engine factory tests ---


@pytest.mark.asyncio
async def test_create_engine_and_session():
    engine, session_factory = create_engine_and_session("sqlite+aiosqlite://")
    await init_db(engine)

    async with session_factory() as session:
        task = Task(uuid="engine_test_abcdefghij", title="Engine test")
        session.add(task)
        await session.commit()

        result = await session.execute(select(Task).where(Task.uuid == "engine_test_abcdefghij"))
        assert result.scalar_one().title == "Engine test"

    await engine.dispose()


# --- Cloud client protocol ---


def test_fake_client_satisfies_protocol():
    """FakeCloudClient should structurally satisfy CloudClientProtocol."""
    client: CloudClientProtocol = FakeCloudClient()
    assert hasattr(client, "authenticate")
    assert hasattr(client, "get_items")
    assert hasattr(client, "commit")
    assert hasattr(client, "close")


# --- Parse notes ---


def test_parse_notes_empty():
    assert parse_notes(None) == ""
    assert parse_notes("") == ""


def test_parse_notes_dict():
    assert parse_notes({"_t": "tx", "v": "hello", "t": 1}) == "hello"


def test_parse_notes_xml():
    assert parse_notes('<note xml:space="preserve">My note</note>') == "My note"


def test_parse_notes_html_fallback():
    assert parse_notes("<b>bold</b> text") == "bold text"


# --- TaskService ---


@pytest.mark.asyncio
async def test_task_service_create_and_list(sdk_session):
    svc = TaskService()
    created = await svc.create_task(
        sdk_session,
        title="SDK created",
        notes=None,
        status=0,
        schedule=1,
        type=0,
        area_uuid=None,
        project_uuid=None,
        heading_uuid=None,
        deadline=None,
        start_date=None,
    )
    assert created["title"] == "SDK created"
    assert len(created["uuid"]) == 22

    tasks = await svc.list_tasks(sdk_session)
    assert len(tasks) == 1
    assert tasks[0]["title"] == "SDK created"


@pytest.mark.asyncio
async def test_task_service_update(sdk_session):
    svc = TaskService()
    sdk_session.add(Task(uuid="sdk_upd_task_abcdefgh", title="Original"))
    await sdk_session.commit()

    updated = await svc.update_task(sdk_session, "sdk_upd_task_abcdefgh", {"title": "Changed"})
    assert updated["title"] == "Changed"


@pytest.mark.asyncio
async def test_task_service_delete(sdk_session):
    svc = TaskService()
    sdk_session.add(Task(uuid="sdk_del_task_abcdefgh", title="To delete"))
    await sdk_session.commit()

    await svc.delete_task(sdk_session, "sdk_del_task_abcdefgh")

    result = await sdk_session.execute(select(Task).where(Task.uuid == "sdk_del_task_abcdefgh"))
    assert result.scalar_one().trashed is True


@pytest.mark.asyncio
async def test_task_service_not_found_raises_sdk_error(sdk_session):
    svc = TaskService()
    with pytest.raises(EntityNotFoundError):
        await svc.get_task(sdk_session, "missing-task")


@pytest.mark.asyncio
async def test_task_service_search_tasks(sdk_session):
    svc = TaskService()
    sdk_session.add(Task(uuid="sdk_srch_milk_abcdefg", title="Buy milk"))
    sdk_session.add(Task(uuid="sdk_srch_dog__abcdefg", title="Walk the dog"))
    sdk_session.add(Task(uuid="sdk_srch_bread_abcdef", title="Buy bread", notes="From the bakery"))
    await sdk_session.commit()

    matches = await svc.search_tasks(sdk_session, query="buy")
    titles = {t["title"] for t in matches}
    assert titles == {"Buy milk", "Buy bread"}

    notes_match = await svc.search_tasks(sdk_session, query="bakery")
    assert [t["title"] for t in notes_match] == ["Buy bread"]


@pytest.mark.asyncio
async def test_task_service_search_tasks_empty_query(sdk_session):
    svc = TaskService()
    sdk_session.add(Task(uuid="sdk_srch_empty_abcdef", title="Anything"))
    await sdk_session.commit()
    assert await svc.search_tasks(sdk_session, query="") == []


@pytest.mark.asyncio
async def test_task_service_list_projects(sdk_session):
    svc = TaskService()
    sdk_session.add(Task(uuid="sdk_proj_one1abcdefgh", title="Proj 1", type=1, status=0))
    sdk_session.add(Task(uuid="sdk_proj_done_abcdefg", title="Proj done", type=1, status=3))
    sdk_session.add(Task(uuid="sdk_just_task_abcdefg", title="Just a task", type=0))
    await sdk_session.commit()

    active = await svc.list_projects(sdk_session)
    assert [p["title"] for p in active] == ["Proj 1"]

    all_projects = await svc.list_projects(sdk_session, include_completed=True)
    titles = {p["title"] for p in all_projects}
    assert titles == {"Proj 1", "Proj done"}


@pytest.mark.asyncio
async def test_task_service_search_advanced_combines_predicates(sdk_session):
    svc = TaskService()
    sdk_session.add(Task(
        uuid="sdk_adv_match__abcdefg", title="Match",
        type=1, status=0, deadline=2000.0, modification_date=1500.0,
    ))
    sdk_session.add(Task(
        uuid="sdk_adv_wrongdl_abcdef", title="Wrong deadline",
        type=1, status=0, deadline=500.0, modification_date=1500.0,
    ))
    sdk_session.add(Task(
        uuid="sdk_adv_wrongty_abcdef", title="Wrong type",
        type=0, status=0, deadline=2000.0, modification_date=1500.0,
    ))
    await sdk_session.commit()

    results = await svc.search_advanced(
        sdk_session,
        type=1,
        deadline_from=1000.0,
        deadline_to=5000.0,
        modified_since=1000.0,
    )
    assert [r["title"] for r in results] == ["Match"]


# --- Sync engine ---


@pytest.mark.asyncio
async def test_pull_sync_creates_task(sdk_session):
    client = FakeCloudClient(
        items=[{"sdk_pull_task_abcdefgh": {"t": 0, "e": "Task6", "p": {"tt": "Pulled task"}}}],
        new_index=1,
    )
    counts = await pull_sync(client, sdk_session)
    assert counts["created"] == 1

    result = await sdk_session.execute(select(Task).where(Task.uuid == "sdk_pull_task_abcdefgh"))
    assert result.scalar_one().title == "Pulled task"


@pytest.mark.asyncio
async def test_push_sync_sends_pending(sdk_session):
    sdk_session.add(SyncState(id=1, history_key="fake-key", head_index=0))
    sdk_session.add(Task(uuid="sdk_push_task_abcdefgh", title="Push me", pending_push=True, status=0, schedule=0))
    await sdk_session.commit()

    client = FakeCloudClient(new_index=5)
    counts = await push_sync(client, sdk_session)
    assert counts["pushed"] == 1
    assert len(client.committed) == 1


@pytest.mark.asyncio
async def test_pull_sync_circuit_open_blocks(sdk_session):
    sdk_session.add(SyncState(
        id=1, history_key="fake-key",
        sync_status="circuit_open",
        circuit_open_until=time.time() + 30,
    ))
    await sdk_session.commit()

    client = FakeCloudClient()
    with pytest.raises(SyncCircuitOpenError):
        await pull_sync(client, sdk_session)
