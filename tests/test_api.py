"""Tests for API endpoints — integration tests through FastAPI test client."""

import os
import time

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
async def test_tasks_accepts_next_api_key_for_rotation(app, monkeypatch):
    app_instance, _ = app
    monkeypatch.setenv("API_KEY_NEXT", "b" * 32)

    transport = ASGITransport(app=app_instance)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": "b" * 32},
    ) as client:
        resp = await client.get("/api/tasks")

    assert resp.status_code == 200


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
    state = SyncState(
        id=1,
        sync_status="synced",
        head_index=42,
        last_sync_at=1700000000.0,
        last_pull_skipped=2,
        sync_errors_total=3,
    )
    db.add(state)
    await db.commit()

    resp = await authed_client.get("/api/sync/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["sync_status"] == "synced"
    assert data["head_index"] == 42
    assert data["last_pull_skipped"] == 2
    assert data["sync_errors_total"] == 3


@pytest.mark.asyncio
async def test_get_sync_status_empty(authed_client):
    resp = await authed_client.get("/api/sync/status")
    assert resp.status_code == 200
    assert resp.json()["sync_status"] == "never"
    assert resp.json()["last_pull_skipped"] == 0
    assert resp.json()["sync_errors_total"] == 0


@pytest.mark.asyncio
async def test_ready_degraded_when_sync_error_threshold_exceeded(client, db, monkeypatch):
    from things_api.config import settings

    monkeypatch.setattr(settings, "readiness_max_sync_errors", 2)

    db.add(SyncState(id=1, sync_status="error", sync_errors_total=3, last_pull_skipped=0))
    await db.commit()

    resp = await client.get("/ready")
    assert resp.status_code == 503
    assert resp.json()["status"] == "degraded"
    assert resp.json()["reason"] == "sync_errors_threshold_exceeded"


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
async def test_create_task_generates_22_char_uuid(authed_client):
    resp = await authed_client.post("/api/tasks", json={"title": "UUID length check"})
    assert resp.status_code == 201
    assert len(resp.json()["uuid"]) == 22


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


@pytest.mark.asyncio
async def test_trigger_sync_returns_409_when_manual_sync_lock_held(authed_client, db, monkeypatch):
    from things_api.config import settings

    monkeypatch.setattr(settings, "things_email", "user@example.com")
    monkeypatch.setattr(settings, "things_password", "secret")

    db.add(SyncState(id=1, manual_sync_lock_until=time.time() + 30))
    await db.commit()

    resp = await authed_client.post("/api/sync")
    assert resp.status_code == 409
    assert "already in progress" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_trigger_sync_returns_503_when_circuit_open(authed_client, db, monkeypatch):
    from things_api.config import settings

    now = time.time()
    db.add(SyncState(id=1, sync_status="circuit_open", circuit_open_until=now + 30))
    await db.commit()

    monkeypatch.setattr(settings, "things_email", "user@example.com")
    monkeypatch.setattr(settings, "things_password", "secret")

    resp = await authed_client.post("/api/sync")
    assert resp.status_code == 503
    assert "Circuit breaker open" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_trigger_sync_releases_manual_lock_after_success(authed_client, db, monkeypatch):
    import things_sdk.cloud.client as client_mod
    import things_sdk.cloud.sync as sync_mod
    from things_api.config import settings

    monkeypatch.setattr(settings, "things_email", "user@example.com")
    monkeypatch.setattr(settings, "things_password", "secret")

    class FakeClient:
        def __init__(self, email: str, password: str):
            self.email = email
            self.password = password

        async def close(self):
            return None

    async def fake_pull_sync(client, session):
        return {"created": 0, "modified": 0, "deleted": 0, "skipped": 0}

    async def fake_push_sync(client, session):
        return {"pushed": 0}

    monkeypatch.setattr(client_mod, "ThingsCloudClient", FakeClient)
    monkeypatch.setattr(sync_mod, "pull_sync", fake_pull_sync)
    monkeypatch.setattr(sync_mod, "push_sync", fake_push_sync)

    resp = await authed_client.post("/api/sync")
    assert resp.status_code == 200

    result = await db.execute(select(SyncState).where(SyncState.id == 1))
    state = result.scalar_one()
    assert state.manual_sync_lock_until is None


@pytest.mark.asyncio
async def test_trigger_sync_closes_cloud_client(authed_client, monkeypatch):
    import things_sdk.cloud.client as client_mod
    import things_sdk.cloud.sync as sync_mod
    from things_api.config import settings

    monkeypatch.setattr(settings, "things_email", "user@example.com")
    monkeypatch.setattr(settings, "things_password", "secret")

    closed = {"value": False}

    class FakeClient:
        def __init__(self, email: str, password: str):
            self.email = email
            self.password = password

        async def close(self):
            closed["value"] = True

    async def fake_pull_sync(client, session):
        return {"created": 0, "modified": 0, "deleted": 0, "skipped": 0}

    async def fake_push_sync(client, session):
        return {"pushed": 0}

    monkeypatch.setattr(client_mod, "ThingsCloudClient", FakeClient)
    monkeypatch.setattr(sync_mod, "pull_sync", fake_pull_sync)
    monkeypatch.setattr(sync_mod, "push_sync", fake_push_sync)

    resp = await authed_client.post("/api/sync")
    assert resp.status_code == 200
    assert closed["value"] is True


@pytest.mark.asyncio
async def test_create_task_with_reminder_time(authed_client, db):
    resp = await authed_client.post(
        "/api/tasks",
        json={"title": "Wake up", "reminder_time": 28800},
    )
    assert resp.status_code == 201
    assert resp.json()["reminder_time"] == 28800


@pytest.mark.asyncio
async def test_update_task_sets_reminder_time(authed_client, db):
    task = Task(uuid="remind_upd_abcdefghijk", title="Original")
    db.add(task)
    await db.commit()

    resp = await authed_client.patch(
        "/api/tasks/remind_upd_abcdefghijk",
        json={"reminder_time": 32400},
    )
    assert resp.status_code == 200
    assert resp.json()["reminder_time"] == 32400
