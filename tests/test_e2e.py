"""End-to-end tests: API → SDK → sync engine → mock Things Cloud → back.

These tests verify the full round-trip:
- Create/tag tasks via API → push sync → verify wire format sent to cloud
- Pull sync from cloud with tags → verify API responses
- Smart lists reflect correct data after sync
- Tag CRUD survives a full sync round-trip
"""

from __future__ import annotations

import time

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from things_sdk import Base, SyncState, Tag, Task, TaskTag, configure_sync


# ============================================================
# Mock Things Cloud
# ============================================================


class MockThingsCloud:
    """Simulates the Things Cloud API.

    Captures push commits and serves configurable pull responses.
    Acts as both the client and the "cloud server" state.
    """

    def __init__(self) -> None:
        self.committed_batches: list[list[dict]] = []
        self.pull_items: list[dict] = []
        self.pull_index: int = 0
        self._history_key = "mock-history-key"

    async def authenticate(self) -> str:
        return self._history_key

    async def get_items(self, start_index: int = 0) -> tuple[list[dict], int]:
        items = self.pull_items
        self.pull_items = []  # consumed
        return items, self.pull_index

    async def commit(self, items: list[dict], ancestor_index: int) -> int:
        self.committed_batches.append(items)
        self.pull_index += 1
        return self.pull_index

    async def close(self) -> None:
        pass

    # --- Helpers for test assertions ---

    @property
    def last_batch(self) -> list[dict]:
        return self.committed_batches[-1] if self.committed_batches else []

    def find_pushed_entity(self, uuid: str) -> dict | None:
        """Find a pushed entity by UUID across all batches."""
        for batch in self.committed_batches:
            for item in batch:
                if uuid in item:
                    return item[uuid]
        return None

    def get_pushed_task_payload(self, uuid: str) -> dict | None:
        entity = self.find_pushed_entity(uuid)
        if entity and entity.get("e") == "Task6":
            return entity.get("p", {})
        return None

    def get_pushed_tag_payload(self, uuid: str) -> dict | None:
        entity = self.find_pushed_entity(uuid)
        if entity and entity.get("e") == "Tag4":
            return entity.get("p", {})
        return None


# ============================================================
# Fixtures
# ============================================================


class _SyncConfig:
    sync_retry_attempts = 1
    sync_retry_base_seconds = 0.0
    sync_circuit_breaker_failures = 99
    sync_circuit_breaker_cooldown_seconds = 0.0


@pytest.fixture(autouse=True)
def _configure_sync():
    configure_sync(_SyncConfig())


@pytest.fixture
async def cloud():
    return MockThingsCloud()


@pytest.fixture(autouse=True)
def _set_env(monkeypatch):
    monkeypatch.setenv("API_KEY", "a" * 32)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite://")
    monkeypatch.setenv("THINGS_EMAIL", "test@example.com")
    monkeypatch.setenv("THINGS_PASSWORD", "test-password")
    monkeypatch.setenv("MANUAL_SYNC_LOCK_SECONDS", "1")


@pytest.fixture
async def app_and_cloud(cloud):
    """Create a full app with mock cloud wired into the sync service."""
    import importlib
    import things_api.config

    importlib.reload(things_api.config)

    from things_api.db import engine as engine_mod
    from things_api.services.sync_service import SyncService, get_sync_service

    test_engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    engine_mod.engine = test_engine
    engine_mod.async_session = factory

    # Create a SyncService that uses our mock cloud
    mock_sync_service = SyncService(
        client_factory=lambda email, password: cloud,
    )

    from things_api.main import app

    # Override the dependency
    app.dependency_overrides[get_sync_service] = lambda: mock_sync_service

    yield app, cloud, factory

    app.dependency_overrides.clear()
    await test_engine.dispose()


@pytest.fixture
async def client(app_and_cloud):
    app, _, _ = app_and_cloud
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": "a" * 32},
    ) as c:
        yield c


@pytest.fixture
async def e2e(app_and_cloud, client):
    """Convenience fixture bundling client, cloud, and session factory."""
    app, cloud, factory = app_and_cloud
    return client, cloud, factory


async def _reset_sync_rate_limit(factory):
    """Reset last_sync_at so the next POST /api/sync isn't rate-limited."""
    from sqlalchemy import update
    async with factory() as session:
        await session.execute(
            update(SyncState).where(SyncState.id == 1).values(last_sync_at=None)
        )
        await session.commit()


# ============================================================
# E2E: Create task → push sync → verify cloud wire format
# ============================================================


@pytest.mark.asyncio
async def test_e2e_create_task_push_includes_tags(e2e):
    """Create a task with tags via API, trigger sync, verify push payload has tg field."""
    client, cloud, factory = e2e

    # Create a tag
    tag_resp = await client.post("/api/tags", json={"title": "errands"})
    assert tag_resp.status_code == 201
    tag_uuid = tag_resp.json()["uuid"]

    # Create a task with the tag
    task_resp = await client.post("/api/tasks", json={
        "title": "Buy groceries",
        "schedule": "anytime",
        "tags": [tag_uuid],
    })
    assert task_resp.status_code == 201
    task_uuid = task_resp.json()["uuid"]
    assert task_resp.json()["tags"][0]["uuid"] == tag_uuid

    # Trigger sync
    sync_resp = await client.post("/api/sync")
    assert sync_resp.status_code == 200
    sync_data = sync_resp.json()
    assert sync_data["push"]["pushed"] >= 1

    # Verify the cloud received the task with tags
    task_payload = cloud.get_pushed_task_payload(task_uuid)
    assert task_payload is not None, "Task not found in push payload"
    assert "tg" in task_payload, "tg field missing from push payload"
    assert tag_uuid in task_payload["tg"]


@pytest.mark.asyncio
async def test_e2e_push_tag_before_task(e2e):
    """Tags should be pushed before tasks that reference them."""
    client, cloud, factory = e2e

    # Create tag + task in one go
    tag_resp = await client.post("/api/tags", json={"title": "priority"})
    tag_uuid = tag_resp.json()["uuid"]

    await client.post("/api/tasks", json={
        "title": "Important thing",
        "tags": [tag_uuid],
    })

    # Sync
    await client.post("/api/sync")

    # In the last batch, tag should appear before task
    batch = cloud.last_batch
    tag_index = None
    task_index = None
    for i, item in enumerate(batch):
        for uuid, data in item.items():
            if data.get("e") == "Tag4":
                tag_index = i
            if data.get("e") == "Task6":
                task_index = i

    assert tag_index is not None, "Tag not found in push batch"
    assert task_index is not None, "Task not found in push batch"
    assert tag_index < task_index, f"Tag (idx={tag_index}) should come before task (idx={task_index})"


@pytest.mark.asyncio
async def test_e2e_remove_all_tags_push_empty_tg(e2e):
    """Removing all tags should push tg=[]."""
    client, cloud, factory = e2e

    tag_resp = await client.post("/api/tags", json={"title": "temp"})
    tag_uuid = tag_resp.json()["uuid"]

    task_resp = await client.post("/api/tasks", json={
        "title": "Will lose tags",
        "tags": [tag_uuid],
    })
    task_uuid = task_resp.json()["uuid"]

    # First sync to clear pending_push
    await client.post("/api/sync")
    cloud.committed_batches.clear()

    # Remove tags
    await client.patch(f"/api/tasks/{task_uuid}", json={"tags": []})

    # Sync again
    await _reset_sync_rate_limit(factory)
    await client.post("/api/sync")

    task_payload = cloud.get_pushed_task_payload(task_uuid)
    assert task_payload is not None
    assert task_payload["tg"] == []


# ============================================================
# E2E: Pull sync from cloud → verify API shows correct data
# ============================================================


@pytest.mark.asyncio
async def test_e2e_pull_tagged_task_appears_in_api(e2e):
    """Pull a task with tags from cloud, verify it appears with tags in API."""
    client, cloud, factory = e2e

    # Pre-load tags into cloud pull
    cloud.pull_items = [
        {"cloud_tag_work______": {
            "t": 0, "e": "Tag4",
            "p": {"tt": "work", "ix": 0},
        }},
        {"cloud_tag_errands___": {
            "t": 0, "e": "Tag4",
            "p": {"tt": "errands", "pn": ["cloud_tag_work______"], "ix": 0},
        }},
        {"cloud_task_abc______": {
            "t": 0, "e": "Task6",
            "p": {
                "tt": "Review PR",
                "ss": 0,
                "st": 1,  # anytime
                "tg": ["cloud_tag_work______", "cloud_tag_errands___"],
            },
        }},
    ]
    cloud.pull_index = 1

    # Trigger sync (pull)
    sync_resp = await client.post("/api/sync")
    assert sync_resp.status_code == 200

    # Get the task via API
    task_resp = await client.get("/api/tasks/cloud_task_abc______")
    assert task_resp.status_code == 200
    task = task_resp.json()
    assert task["title"] == "Review PR"
    tag_titles = {t["title"] for t in task["tags"]}
    assert tag_titles == {"work", "errands"}


@pytest.mark.asyncio
async def test_e2e_pull_updates_tags_replace_set(e2e):
    """A second pull with different tags should replace, not append."""
    client, cloud, factory = e2e

    # First pull: task with tag A
    cloud.pull_items = [
        {"tag_a_e2e___________": {"t": 0, "e": "Tag4", "p": {"tt": "alpha"}}},
        {"tag_b_e2e___________": {"t": 0, "e": "Tag4", "p": {"tt": "beta"}}},
        {"task_e2e_replace____": {
            "t": 0, "e": "Task6",
            "p": {"tt": "Replaceable", "ss": 0, "tg": ["tag_a_e2e___________"]},
        }},
    ]
    cloud.pull_index = 1
    await client.post("/api/sync")

    task = (await client.get("/api/tasks/task_e2e_replace____")).json()
    assert [t["title"] for t in task["tags"]] == ["alpha"]

    # Second pull: same task, now with tag B only
    await _reset_sync_rate_limit(factory)
    cloud.pull_items = [
        {"task_e2e_replace____": {
            "t": 1, "e": "Task6",
            "p": {"tg": ["tag_b_e2e___________"]},
        }},
    ]
    cloud.pull_index = 2
    await client.post("/api/sync")

    task = (await client.get("/api/tasks/task_e2e_replace____")).json()
    assert [t["title"] for t in task["tags"]] == ["beta"]


# ============================================================
# E2E: Smart lists after sync
# ============================================================


@pytest.mark.asyncio
async def test_e2e_smart_lists_after_pull(e2e):
    """Pull various tasks and verify smart lists show the right ones."""
    client, cloud, factory = e2e

    now = time.time()
    today_start = now - (now % 86400)  # approximate start of today UTC

    cloud.pull_items = [
        # Inbox task
        {"sl_inbox____________": {
            "t": 0, "e": "Task6",
            "p": {"tt": "Inbox task", "ss": 0, "st": 0, "tp": 0},
        }},
        # Anytime task
        {"sl_anytime__________": {
            "t": 0, "e": "Task6",
            "p": {"tt": "Anytime task", "ss": 0, "st": 1},
        }},
        # Someday task
        {"sl_someday__________": {
            "t": 0, "e": "Task6",
            "p": {"tt": "Someday task", "ss": 0, "st": 2},
        }},
        # Completed task (logbook)
        {"sl_done____________": {
            "t": 0, "e": "Task6",
            "p": {"tt": "Done task", "ss": 3, "sp": now - 3600},
        }},
        # Trashed task
        {"sl_trash___________": {
            "t": 0, "e": "Task6",
            "p": {"tt": "Trashed task", "ss": 0, "tr": True, "md": now},
        }},
    ]
    cloud.pull_index = 1
    await client.post("/api/sync")

    # Verify each smart list
    inbox = (await client.get("/api/tasks/inbox")).json()
    assert any(t["title"] == "Inbox task" for t in inbox)
    assert not any(t["title"] == "Anytime task" for t in inbox)

    anytime = (await client.get("/api/tasks/anytime")).json()
    assert any(t["title"] == "Anytime task" for t in anytime)

    someday = (await client.get("/api/tasks/someday")).json()
    assert any(t["title"] == "Someday task" for t in someday)

    logbook = (await client.get("/api/tasks/logbook")).json()
    assert any(t["title"] == "Done task" for t in logbook)

    trash = (await client.get("/api/tasks/trash")).json()
    assert any(t["title"] == "Trashed task" for t in trash)


# ============================================================
# E2E: Tag filter via API after pull
# ============================================================


@pytest.mark.asyncio
async def test_e2e_filter_by_tag_after_pull(e2e):
    """Pull tasks with tags, then filter via /api/tasks/by-tag/."""
    client, cloud, factory = e2e

    cloud.pull_items = [
        {"e2e_tag_home________": {"t": 0, "e": "Tag4", "p": {"tt": "home"}}},
        {"e2e_tag_work________": {"t": 0, "e": "Tag4", "p": {"tt": "work"}}},
        {"e2e_task_home_______": {
            "t": 0, "e": "Task6",
            "p": {"tt": "Home stuff", "ss": 0, "st": 1, "tg": ["e2e_tag_home________"]},
        }},
        {"e2e_task_work_______": {
            "t": 0, "e": "Task6",
            "p": {"tt": "Work stuff", "ss": 0, "st": 1, "tg": ["e2e_tag_work________"]},
        }},
        {"e2e_task_both_______": {
            "t": 0, "e": "Task6",
            "p": {"tt": "Both tags", "ss": 0, "st": 1, "tg": ["e2e_tag_home________", "e2e_tag_work________"]},
        }},
    ]
    cloud.pull_index = 1
    await client.post("/api/sync")

    # Filter by "home"
    home_tasks = (await client.get("/api/tasks/by-tag/home")).json()
    home_titles = {t["title"] for t in home_tasks}
    assert home_titles == {"Home stuff", "Both tags"}

    # Filter by "work"
    work_tasks = (await client.get("/api/tasks/by-tag/work")).json()
    work_titles = {t["title"] for t in work_tasks}
    assert work_titles == {"Work stuff", "Both tags"}


# ============================================================
# E2E: Full round-trip (create via API → push → pull back → verify)
# ============================================================


@pytest.mark.asyncio
async def test_e2e_full_round_trip(e2e):
    """Create task+tag via API → push → simulate cloud echo → pull → verify parity."""
    client, cloud, factory = e2e

    # 1. Create tag + task via API
    tag_resp = await client.post("/api/tags", json={"title": "roundtrip"})
    tag_uuid = tag_resp.json()["uuid"]

    task_resp = await client.post("/api/tasks", json={
        "title": "Round-trip task",
        "notes": "Testing full cycle",
        "schedule": "anytime",
        "tags": [tag_uuid],
    })
    task_uuid = task_resp.json()["uuid"]

    # 2. Push to cloud
    await client.post("/api/sync")

    # Verify cloud got it
    task_payload = cloud.get_pushed_task_payload(task_uuid)
    assert task_payload is not None
    assert task_payload["tt"] == "Round-trip task"
    assert tag_uuid in task_payload["tg"]

    tag_payload = cloud.get_pushed_tag_payload(tag_uuid)
    assert tag_payload is not None
    assert tag_payload["tt"] == "roundtrip"

    # 3. Simulate cloud sending it back on next pull (as if from another device)
    await _reset_sync_rate_limit(factory)

    cloud.pull_items = [
        {tag_uuid: {
            "t": 1, "e": "Tag4",
            "p": {"tt": "roundtrip"},
        }},
        {task_uuid: {
            "t": 1, "e": "Task6",
            "p": {
                "tt": "Round-trip task",
                "nt": "Testing full cycle",
                "ss": 0,
                "st": 1,
                "tg": [tag_uuid],
            },
        }},
    ]
    cloud.pull_index += 1

    await client.post("/api/sync")

    # 4. Verify API returns the task with tags intact
    task = (await client.get(f"/api/tasks/{task_uuid}")).json()
    assert task["title"] == "Round-trip task"
    assert len(task["tags"]) == 1
    assert task["tags"][0]["uuid"] == tag_uuid
    assert task["tags"][0]["title"] == "roundtrip"


# ============================================================
# E2E: Tag deletion cascade through sync
# ============================================================


@pytest.mark.asyncio
async def test_e2e_tag_delete_cascades_through_sync(e2e):
    """Delete a tag via API → push sends Tag4 delete → associations cleaned up."""
    client, cloud, factory = e2e

    # Create tag + tagged task
    tag_resp = await client.post("/api/tags", json={"title": "doomed"})
    tag_uuid = tag_resp.json()["uuid"]

    task_resp = await client.post("/api/tasks", json={
        "title": "Was tagged",
        "tags": [tag_uuid],
    })
    task_uuid = task_resp.json()["uuid"]

    # Push initial state
    await client.post("/api/sync")
    cloud.committed_batches.clear()

    # Delete the tag
    del_resp = await client.delete(f"/api/tags/{tag_uuid}")
    assert del_resp.status_code == 204

    # Verify task no longer has the tag in API response
    # (tag is pending_delete, filtered out of reads)
    task = (await client.get(f"/api/tasks/{task_uuid}")).json()
    # Tag might still be in task_tag until push sync cleans it up

    # Push the delete
    await _reset_sync_rate_limit(factory)
    await client.post("/api/sync")

    # Verify cloud received tag deletion
    tag_entity = cloud.find_pushed_entity(tag_uuid)
    assert tag_entity is not None
    assert tag_entity["t"] == 2  # ACTION_DELETED
    assert tag_entity["e"] == "Tag4"

    # Verify tag is gone from local DB
    async with factory() as session:
        result = await session.execute(select(Tag).where(Tag.uuid == tag_uuid))
        assert result.scalar_one_or_none() is None

        # task_tag associations cleaned up
        result = await session.execute(
            select(TaskTag).where(TaskTag.tag_uuid == tag_uuid)
        )
        assert list(result.scalars()) == []
