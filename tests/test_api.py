"""Tests for API endpoints — integration tests through FastAPI test client."""

import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from things_api.db.models import Area, Base, ChecklistItem, SyncState, Tag, Task


@pytest.fixture(autouse=True)
def set_api_key(monkeypatch):
    monkeypatch.setenv("API_KEY", "a" * 32)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite://")


@pytest.fixture
async def app():
    """Create a fresh app with in-memory DB for each test."""
    # Re-import to pick up monkeypatched env vars
    import importlib
    import things_api.config
    importlib.reload(things_api.config)

    from things_api.config import settings
    from things_api.db import engine as engine_mod

    # Create in-memory engine
    test_engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    test_session_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Patch the engine module
    engine_mod.engine = test_engine
    engine_mod.async_session = test_session_factory

    from things_api.main import app
    yield app, test_session_factory

    await test_engine.dispose()


@pytest.fixture
async def client(app):
    app_instance, _ = app
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def authed_client(app):
    app_instance, _ = app
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": "a" * 32},
    ) as c:
        yield c


@pytest.fixture
async def db(app):
    _, session_factory = app
    async with session_factory() as session:
        yield session


@pytest.mark.asyncio
async def test_health_no_auth_required(client):
    resp = await client.get("/health")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_tasks_returns_401_without_key(client):
    resp = await client.get("/api/tasks")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_tasks_returns_200_with_valid_key(authed_client, db):
    resp = await authed_client.get("/api/tasks")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_tasks_returns_tasks(authed_client, db):
    task = Task(uuid="api_task_001abcdefghi", title="Test task", status=0, schedule=1)
    db.add(task)
    await db.commit()

    resp = await authed_client.get("/api/tasks")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "Test task"
    assert data[0]["uuid"] == "api_task_001abcdefghi"


@pytest.mark.asyncio
async def test_get_task_by_id(authed_client, db):
    task = Task(uuid="api_task_002abcdefghi", title="Specific task")
    db.add(task)
    await db.commit()

    resp = await authed_client.get("/api/tasks/api_task_002abcdefghi")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Specific task"


@pytest.mark.asyncio
async def test_get_task_404(authed_client):
    resp = await authed_client.get("/api/tasks/nonexistent_uuid_12345")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_sync_status(authed_client, db):
    state = SyncState(id=1, sync_status="synced", head_index=42, last_sync_at=1700000000.0)
    db.add(state)
    await db.commit()

    resp = await authed_client.get("/api/sync/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["sync_status"] == "synced"
    assert data["head_index"] == 42


@pytest.mark.asyncio
async def test_get_sync_status_empty(authed_client):
    resp = await authed_client.get("/api/sync/status")
    assert resp.status_code == 200
    assert resp.json()["sync_status"] == "never"


# --- Write endpoints ---


@pytest.mark.asyncio
async def test_create_task(authed_client, db):
    resp = await authed_client.post("/api/tasks", json={"title": "New task", "schedule": 1})
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "New task"
    assert data["schedule"] == "anytime"
    assert data["uuid"]  # auto-generated
    assert data["status"] == "pending"  # default pending


@pytest.mark.asyncio
async def test_create_task_validates_title(authed_client):
    resp = await authed_client.post("/api/tasks", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_task(authed_client, db):
    task = Task(uuid="upd_task_001abcdefghij", title="Old title")
    db.add(task)
    await db.commit()

    resp = await authed_client.patch(
        "/api/tasks/upd_task_001abcdefghij",
        json={"title": "New title", "status": 3},
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "New title"
    assert resp.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_update_task_404(authed_client):
    resp = await authed_client.patch("/api/tasks/nonexistent_uuid_12345", json={"title": "x"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_task(authed_client, db):
    task = Task(uuid="del_task_001abcdefghij", title="To delete")
    db.add(task)
    await db.commit()

    resp = await authed_client.delete("/api/tasks/del_task_001abcdefghij")
    assert resp.status_code == 204

    db.expire_all()
    result = await db.execute(select(Task).where(Task.uuid == "del_task_001abcdefghij"))
    deleted = result.scalar_one_or_none()
    assert deleted is not None
    assert deleted.trashed is True


@pytest.mark.asyncio
async def test_create_task_sets_pending_push(authed_client, db):
    resp = await authed_client.post("/api/tasks", json={"title": "Push me"})
    uuid = resp.json()["uuid"]

    result = await db.execute(select(Task).where(Task.uuid == uuid))
    task = result.scalar_one()
    assert task.pending_push is True


@pytest.mark.asyncio
async def test_update_task_sets_pending_push(authed_client, db):
    task = Task(uuid="push_upd_01abcdefghijk", title="Original", pending_push=False)
    db.add(task)
    await db.commit()

    await authed_client.patch("/api/tasks/push_upd_01abcdefghijk", json={"title": "Changed"})

    db.expire_all()
    result = await db.execute(select(Task).where(Task.uuid == "push_upd_01abcdefghijk"))
    updated = result.scalar_one()
    assert updated.pending_push is True


@pytest.mark.asyncio
async def test_create_task_with_string_enums(authed_client, db):
    resp = await authed_client.post(
        "/api/tasks",
        json={"title": "String enums", "status": "completed", "schedule": "someday", "type": "project"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "completed"
    assert data["schedule"] == "someday"
    assert data["type"] == "project"


@pytest.mark.asyncio
async def test_update_task_with_string_enum(authed_client, db):
    task = Task(uuid="enum_upd_01abcdefghijk", title="Test", status=0, schedule=0)
    db.add(task)
    await db.commit()

    resp = await authed_client.patch(
        "/api/tasks/enum_upd_01abcdefghijk",
        json={"status": "cancelled", "schedule": "anytime"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"
    assert resp.json()["schedule"] == "anytime"
