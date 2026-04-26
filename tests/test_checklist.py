"""Tests for checklist item write operations — SDK, wire format, sync, and API."""

import time

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from things_sdk import Base, ChecklistItem, Task, TaskService, configure_sync
from things_sdk.cloud.protocol import is_valid_things_uuid
from things_sdk.cloud.sync import _checklist_item_to_wire, pull_sync, push_sync
from things_sdk.errors import EntityNotFoundError


class _SyncConfig:
    sync_retry_attempts = 1
    sync_retry_base_seconds = 0.0
    sync_circuit_breaker_failures = 99
    sync_circuit_breaker_cooldown_seconds = 0.0


@pytest.fixture(autouse=True)
def _configure():
    configure_sync(_SyncConfig())


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def svc():
    return TaskService()


class FakeCloudClient:
    def __init__(self, items=None, new_index=1):
        self.items = items or []
        self.new_index = new_index
        self.committed = []
    async def authenticate(self): return "key"
    async def get_items(self, start_index=0): return self.items, self.new_index
    async def commit(self, items, ancestor_index):
        self.committed.extend(items)
        return self.new_index
    async def close(self): pass


# ============================================================
# SDK: Checklist CRUD
# ============================================================


class TestChecklistCRUD:
    @pytest.mark.asyncio
    async def test_create_checklist_item(self, session, svc):
        task = await svc.create_task(
            session, title="Parent", notes=None, status=0, schedule=0, type=0,
            area_uuid=None, project_uuid=None, heading_uuid=None,
            deadline=None, start_date=None,
        )
        item = await svc.create_checklist_item(session, task_uuid=task["uuid"], title="Sub-task")
        assert item["title"] == "Sub-task"
        assert item["status"] == "pending"
        assert item["task_uuid"] == task["uuid"]
        assert is_valid_things_uuid(item["uuid"])

    @pytest.mark.asyncio
    async def test_create_checklist_item_task_not_found(self, session, svc):
        with pytest.raises(EntityNotFoundError):
            await svc.create_checklist_item(session, task_uuid="nonexistent___________", title="X")

    @pytest.mark.asyncio
    async def test_complete_checklist_item(self, session, svc):
        task = await svc.create_task(
            session, title="Parent", notes=None, status=0, schedule=0, type=0,
            area_uuid=None, project_uuid=None, heading_uuid=None,
            deadline=None, start_date=None,
        )
        item = await svc.create_checklist_item(session, task_uuid=task["uuid"], title="Do this")
        completed = await svc.complete_checklist_item(session, item["uuid"])
        assert completed["status"] == "completed"
        assert completed["stop_date"] is not None

    @pytest.mark.asyncio
    async def test_uncomplete_checklist_item(self, session, svc):
        task = await svc.create_task(
            session, title="Parent", notes=None, status=0, schedule=0, type=0,
            area_uuid=None, project_uuid=None, heading_uuid=None,
            deadline=None, start_date=None,
        )
        item = await svc.create_checklist_item(session, task_uuid=task["uuid"], title="Undo this")
        await svc.complete_checklist_item(session, item["uuid"])
        uncompleted = await svc.uncomplete_checklist_item(session, item["uuid"])
        assert uncompleted["status"] == "pending"
        assert uncompleted["stop_date"] is None

    @pytest.mark.asyncio
    async def test_complete_nonexistent_item(self, session, svc):
        with pytest.raises(EntityNotFoundError):
            await svc.complete_checklist_item(session, "nonexistent___________")

    @pytest.mark.asyncio
    async def test_checklist_appears_in_task_checklist(self, session, svc):
        task = await svc.create_task(
            session, title="Parent", notes=None, status=0, schedule=0, type=0,
            area_uuid=None, project_uuid=None, heading_uuid=None,
            deadline=None, start_date=None,
        )
        await svc.create_checklist_item(session, task_uuid=task["uuid"], title="Item 1")
        await svc.create_checklist_item(session, task_uuid=task["uuid"], title="Item 2")
        checklist = await svc.get_task_checklist(session, task["uuid"])
        assert len(checklist) == 2
        assert {c["title"] for c in checklist} == {"Item 1", "Item 2"}


# ============================================================
# Wire Format: ChecklistItem3
# ============================================================


class TestChecklistWireFormat:
    def _make_item(self, **overrides) -> ChecklistItem:
        now = time.time()
        defaults = dict(
            uuid="test_ci_base58_______", title="Test", status=0, index=0,
            task_uuid="test_task_base58_____", stop_date=None,
            creation_date=now, modification_date=now,
            pending_push=True, is_new=True,
        )
        defaults.update(overrides)
        return ChecklistItem(**defaults)

    def test_create_wire_format(self):
        item = self._make_item(is_new=True)
        wire = _checklist_item_to_wire(item)
        data = list(wire.values())[0]
        assert data["t"] == 0  # ACTION_CREATED
        assert data["e"] == "ChecklistItem3"
        p = data["p"]
        assert p["tt"] == "Test"
        assert p["ss"] == 0
        assert p["ts"] == ["test_task_base58_____"]
        assert p["lt"] is False
        assert p["xx"] == {"sn": {}, "_t": "oo"}
        assert "cd" in p
        assert "md" in p

    def test_complete_wire_format(self):
        now = time.time()
        item = self._make_item(is_new=False, status=3, stop_date=now)
        wire = _checklist_item_to_wire(item)
        data = list(wire.values())[0]
        assert data["t"] == 1  # ACTION_MODIFIED
        p = data["p"]
        assert p["ss"] == 3
        assert p["sp"] == now
        assert "md" in p
        # Partial update — no tt, ts, ix etc
        assert "tt" not in p
        assert "ts" not in p

    def test_uncomplete_wire_format(self):
        item = self._make_item(is_new=False, status=0, stop_date=None)
        wire = _checklist_item_to_wire(item)
        data = list(wire.values())[0]
        p = data["p"]
        assert p["ss"] == 0
        assert p["sp"] is None


# ============================================================
# Push Sync: Checklist items included
# ============================================================


class TestChecklistPushSync:
    @pytest.mark.asyncio
    async def test_push_includes_checklist_items(self, session):
        now = time.time()
        session.add(Task(uuid="task_for_cl__________", title="Parent", status=0, schedule=0))
        session.add(ChecklistItem(
            uuid="cl_item_push_________", title="Push me", status=0, index=0,
            task_uuid="task_for_cl__________", creation_date=now, modification_date=now,
            pending_push=True, is_new=True,
        ))
        await session.commit()

        client = FakeCloudClient(new_index=2)
        counts = await push_sync(client, session)
        assert counts["checklist_pushed"] == 1

        # Verify wire format
        found = False
        for item in client.committed:
            if "cl_item_push_________" in item:
                data = item["cl_item_push_________"]
                assert data["e"] == "ChecklistItem3"
                assert data["t"] == 0
                found = True
        assert found

    @pytest.mark.asyncio
    async def test_push_clears_pending_flag(self, session):
        now = time.time()
        session.add(Task(uuid="task_cl_flag_________", title="Parent", status=0, schedule=0))
        session.add(ChecklistItem(
            uuid="cl_flag_test_________", title="Flag", status=0, index=0,
            task_uuid="task_cl_flag_________", creation_date=now, modification_date=now,
            pending_push=True, is_new=True,
        ))
        await session.commit()

        await push_sync(FakeCloudClient(new_index=2), session)

        result = await session.execute(select(ChecklistItem).where(ChecklistItem.uuid == "cl_flag_test_________"))
        ci = result.scalar_one()
        assert ci.pending_push is False
        assert ci.is_new is False


# ============================================================
# Pull Sync: Checklist items
# ============================================================


class TestChecklistPullSync:
    @pytest.mark.asyncio
    async def test_pull_creates_checklist_item(self, session):
        session.add(Task(uuid="task_pull_cl__________", title="Parent"))
        await session.commit()

        client = FakeCloudClient(items=[
            {"new_cl_item__________": {
                "t": 0, "e": "ChecklistItem3",
                "p": {"tt": "Pulled item", "ss": 0, "ix": -100,
                       "ts": ["task_pull_cl__________"], "sp": None,
                       "cd": 1777000000.0, "md": 1777000000.0,
                       "lt": False, "xx": {"sn": {}, "_t": "oo"}},
            }},
        ], new_index=1)
        await pull_sync(client, session)

        result = await session.execute(select(ChecklistItem).where(ChecklistItem.uuid == "new_cl_item__________"))
        ci = result.scalar_one()
        assert ci.title == "Pulled item"
        assert ci.task_uuid == "task_pull_cl__________"

    @pytest.mark.asyncio
    async def test_pull_completes_checklist_item(self, session):
        session.add(Task(uuid="task_cl_comp_________", title="Parent"))
        session.add(ChecklistItem(uuid="cl_to_complete_______", title="Do this",
                                   status=0, task_uuid="task_cl_comp_________"))
        await session.commit()

        client = FakeCloudClient(items=[
            {"cl_to_complete_______": {
                "t": 1, "e": "ChecklistItem3",
                "p": {"ss": 3, "sp": 1777100000.0, "md": 1777100000.0},
            }},
        ], new_index=1)
        await pull_sync(client, session)

        result = await session.execute(select(ChecklistItem).where(ChecklistItem.uuid == "cl_to_complete_______"))
        ci = result.scalar_one()
        assert ci.status == 3
        assert ci.stop_date == 1777100000.0

    @pytest.mark.asyncio
    async def test_pull_uncompletes_checklist_item(self, session):
        session.add(Task(uuid="task_cl_uncomp_______", title="Parent"))
        session.add(ChecklistItem(uuid="cl_to_uncomp_________", title="Undo",
                                   status=3, stop_date=1777000000.0,
                                   task_uuid="task_cl_uncomp_______"))
        await session.commit()

        client = FakeCloudClient(items=[
            {"cl_to_uncomp_________": {
                "t": 1, "e": "ChecklistItem3",
                "p": {"ss": 0, "sp": None, "md": 1777200000.0},
            }},
        ], new_index=1)
        await pull_sync(client, session)

        result = await session.execute(select(ChecklistItem).where(ChecklistItem.uuid == "cl_to_uncomp_________"))
        ci = result.scalar_one()
        assert ci.status == 0
        assert ci.stop_date is None


# ============================================================
# API: Checklist endpoints
# ============================================================


import things_api.config
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def set_api_key(monkeypatch):
    monkeypatch.setenv("API_KEY", "a" * 32)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite://")


@pytest.fixture
async def api_app():
    import importlib
    importlib.reload(things_api.config)
    from things_api.db import engine as engine_mod
    test_engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    engine_mod.engine = test_engine
    engine_mod.async_session = factory
    from things_api.main import app
    yield app
    await test_engine.dispose()


@pytest.fixture
async def authed_client(api_app):
    transport = ASGITransport(app=api_app)
    async with AsyncClient(transport=transport, base_url="http://test",
                           headers={"X-API-Key": "a" * 32}) as c:
        yield c


class TestChecklistAPI:
    @pytest.mark.asyncio
    async def test_api_create_checklist_item(self, authed_client):
        task = (await authed_client.post("/api/tasks", json={"title": "Parent"})).json()
        resp = await authed_client.post(f"/api/tasks/{task['uuid']}/checklist", json={"title": "Sub-item"})
        assert resp.status_code == 201
        assert resp.json()["title"] == "Sub-item"

    @pytest.mark.asyncio
    async def test_api_complete_checklist_item(self, authed_client):
        task = (await authed_client.post("/api/tasks", json={"title": "Parent"})).json()
        item = (await authed_client.post(f"/api/tasks/{task['uuid']}/checklist", json={"title": "Check me"})).json()
        resp = await authed_client.post(f"/api/checklist/{item['uuid']}/complete")
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    @pytest.mark.asyncio
    async def test_api_uncomplete_checklist_item(self, authed_client):
        task = (await authed_client.post("/api/tasks", json={"title": "Parent"})).json()
        item = (await authed_client.post(f"/api/tasks/{task['uuid']}/checklist", json={"title": "Uncheck me"})).json()
        await authed_client.post(f"/api/checklist/{item['uuid']}/complete")
        resp = await authed_client.post(f"/api/checklist/{item['uuid']}/uncomplete")
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending"

    @pytest.mark.asyncio
    async def test_api_checklist_not_found(self, authed_client):
        resp = await authed_client.post("/api/checklist/nonexistent___________/complete")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_api_create_checklist_task_not_found(self, authed_client):
        resp = await authed_client.post("/api/tasks/nonexistent___________/checklist", json={"title": "X"})
        assert resp.status_code == 404
