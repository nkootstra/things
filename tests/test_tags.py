"""Tests for first-class tags — SDK, sync, and API."""

import time

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from things_sdk import Base, Tag, Task, TaskTag, TaskService, configure_sync
from things_sdk.tags import AmbiguousTagError, TagService
from things_sdk.cloud.sync import pull_sync, push_sync


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
async def session():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def tag_svc():
    return TagService()


@pytest.fixture
def task_svc():
    return TaskService()


class FakeCloudClient:
    def __init__(self, items=None, new_index=1):
        self.items = items or []
        self.new_index = new_index
        self.committed = []

    async def authenticate(self):
        return "history-key-123"

    async def get_items(self, start_index=0):
        return self.items, self.new_index

    async def commit(self, items, ancestor_index):
        self.committed.extend(items)
        return self.new_index

    async def close(self):
        pass


# ============================================================
# TagService CRUD Tests
# ============================================================


@pytest.mark.asyncio
async def test_create_tag(session, tag_svc):
    tag = await tag_svc.create_tag(session, title="work")
    assert tag["title"] == "work"
    assert tag["uuid"]
    assert tag["parent_uuid"] is None


@pytest.mark.asyncio
async def test_create_child_tag(session, tag_svc):
    parent = await tag_svc.create_tag(session, title="work")
    child = await tag_svc.create_tag(session, title="errands", parent=parent["uuid"])
    assert child["parent_uuid"] == parent["uuid"]


@pytest.mark.asyncio
async def test_create_child_by_name(session, tag_svc):
    parent = await tag_svc.create_tag(session, title="work")
    child = await tag_svc.create_tag(session, title="errands", parent="work")
    assert child["parent_uuid"] == parent["uuid"]


@pytest.mark.asyncio
async def test_update_tag(session, tag_svc):
    tag = await tag_svc.create_tag(session, title="old")
    updated = await tag_svc.update_tag(session, tag["uuid"], title="new")
    assert updated["title"] == "new"


@pytest.mark.asyncio
async def test_delete_tag(session, tag_svc):
    tag = await tag_svc.create_tag(session, title="temp")
    await tag_svc.delete_tag(session, tag["uuid"])
    # Should be marked for deletion, not in list
    tags = await tag_svc.list_tags(session)
    assert all(t["uuid"] != tag["uuid"] for t in tags)


@pytest.mark.asyncio
async def test_delete_tag_not_found(session, tag_svc):
    from things_sdk import EntityNotFoundError
    with pytest.raises(EntityNotFoundError):
        await tag_svc.delete_tag(session, "nonexistent_tag_id___")


# ============================================================
# Tag Resolution Tests
# ============================================================


@pytest.mark.asyncio
async def test_resolve_by_uuid(session, tag_svc):
    tag = await tag_svc.create_tag(session, title="work")
    resolved = await tag_svc.resolve_tag(session, tag["uuid"])
    assert resolved["uuid"] == tag["uuid"]


@pytest.mark.asyncio
async def test_resolve_by_name(session, tag_svc):
    tag = await tag_svc.create_tag(session, title="work")
    resolved = await tag_svc.resolve_tag(session, "work")
    assert resolved["uuid"] == tag["uuid"]


@pytest.mark.asyncio
async def test_resolve_hierarchical_name(session, tag_svc):
    parent = await tag_svc.create_tag(session, title="work")
    child = await tag_svc.create_tag(session, title="errands", parent=parent["uuid"])
    resolved = await tag_svc.resolve_tag(session, "work/errands")
    assert resolved["uuid"] == child["uuid"]


@pytest.mark.asyncio
async def test_resolve_ambiguous_name_raises(session, tag_svc):
    work = await tag_svc.create_tag(session, title="work")
    home = await tag_svc.create_tag(session, title="home")
    await tag_svc.create_tag(session, title="errands", parent=work["uuid"])
    await tag_svc.create_tag(session, title="errands", parent=home["uuid"])

    with pytest.raises(AmbiguousTagError) as exc_info:
        await tag_svc.resolve_tag(session, "errands")
    assert "work/errands" in str(exc_info.value)
    assert "home/errands" in str(exc_info.value)


@pytest.mark.asyncio
async def test_resolve_not_found(session, tag_svc):
    from things_sdk import EntityNotFoundError
    with pytest.raises(EntityNotFoundError):
        await tag_svc.resolve_tag(session, "nonexistent")


# ============================================================
# Tag Descendants Tests
# ============================================================


@pytest.mark.asyncio
async def test_get_descendants(session, tag_svc):
    parent = await tag_svc.create_tag(session, title="work")
    child = await tag_svc.create_tag(session, title="project", parent=parent["uuid"])
    grandchild = await tag_svc.create_tag(session, title="subtask", parent=child["uuid"])

    descendants = await tag_svc.get_descendants(session, parent["uuid"])
    assert child["uuid"] in descendants
    assert grandchild["uuid"] in descendants
    assert parent["uuid"] not in descendants


# ============================================================
# Task ↔ Tag Association Tests
# ============================================================


@pytest.mark.asyncio
async def test_create_task_with_tags(session, task_svc, tag_svc):
    tag = await tag_svc.create_tag(session, title="work")
    task = await task_svc.create_task(
        session,
        title="Tagged task",
        notes=None,
        status=0,
        schedule=0,
        type=0,
        area_uuid=None,
        project_uuid=None,
        heading_uuid=None,
        deadline=None,
        start_date=None,
        tags=[tag["uuid"]],
    )
    assert len(task["tags"]) == 1
    assert task["tags"][0]["uuid"] == tag["uuid"]
    assert task["tags"][0]["title"] == "work"


@pytest.mark.asyncio
async def test_create_task_with_tag_name(session, task_svc, tag_svc):
    await tag_svc.create_tag(session, title="home")
    task = await task_svc.create_task(
        session,
        title="Task by name",
        notes=None,
        status=0,
        schedule=0,
        type=0,
        area_uuid=None,
        project_uuid=None,
        heading_uuid=None,
        deadline=None,
        start_date=None,
        tags=["home"],
    )
    assert task["tags"][0]["title"] == "home"


@pytest.mark.asyncio
async def test_update_task_tags(session, task_svc, tag_svc):
    tag1 = await tag_svc.create_tag(session, title="work")
    tag2 = await tag_svc.create_tag(session, title="home")

    task = await task_svc.create_task(
        session,
        title="Change tags",
        notes=None,
        status=0,
        schedule=0,
        type=0,
        area_uuid=None,
        project_uuid=None,
        heading_uuid=None,
        deadline=None,
        start_date=None,
        tags=[tag1["uuid"]],
    )
    assert len(task["tags"]) == 1

    updated = await task_svc.update_task(session, task["uuid"], {"tags": [tag2["uuid"]]})
    assert len(updated["tags"]) == 1
    assert updated["tags"][0]["uuid"] == tag2["uuid"]


@pytest.mark.asyncio
async def test_remove_all_tags(session, task_svc, tag_svc):
    tag = await tag_svc.create_tag(session, title="temp")
    task = await task_svc.create_task(
        session,
        title="Remove tags",
        notes=None,
        status=0,
        schedule=0,
        type=0,
        area_uuid=None,
        project_uuid=None,
        heading_uuid=None,
        deadline=None,
        start_date=None,
        tags=[tag["uuid"]],
    )
    updated = await task_svc.update_task(session, task["uuid"], {"tags": []})
    assert updated["tags"] == []


@pytest.mark.asyncio
async def test_create_task_unknown_tag_strict(session, task_svc):
    from things_sdk import EntityNotFoundError
    with pytest.raises(EntityNotFoundError):
        await task_svc.create_task(
            session,
            title="Bad tag",
            notes=None,
            status=0,
            schedule=0,
            type=0,
            area_uuid=None,
            project_uuid=None,
            heading_uuid=None,
            deadline=None,
            start_date=None,
            tags=["nonexistent"],
        )


@pytest.mark.asyncio
async def test_create_task_auto_create_tags(session, task_svc):
    task = await task_svc.create_task(
        session,
        title="Auto tag",
        notes=None,
        status=0,
        schedule=0,
        type=0,
        area_uuid=None,
        project_uuid=None,
        heading_uuid=None,
        deadline=None,
        start_date=None,
        tags=["newcategory"],
        auto_create_tags=True,
    )
    assert len(task["tags"]) == 1
    assert task["tags"][0]["title"] == "newcategory"


# ============================================================
# Tag Filtering Tests
# ============================================================


@pytest.mark.asyncio
async def test_list_tasks_by_tag(session, task_svc, tag_svc):
    tag = await tag_svc.create_tag(session, title="work")
    await task_svc.create_task(
        session, title="Work task", notes=None, status=0, schedule=0, type=0,
        area_uuid=None, project_uuid=None, heading_uuid=None,
        deadline=None, start_date=None, tags=[tag["uuid"]],
    )
    await task_svc.create_task(
        session, title="Untagged task", notes=None, status=0, schedule=0, type=0,
        area_uuid=None, project_uuid=None, heading_uuid=None,
        deadline=None, start_date=None,
    )

    result = await task_svc.list_tasks(session, tag="work")
    assert len(result) == 1
    assert result[0]["title"] == "Work task"


@pytest.mark.asyncio
async def test_list_tasks_by_tag_with_descendants(session, task_svc, tag_svc):
    parent = await tag_svc.create_tag(session, title="work")
    child = await tag_svc.create_tag(session, title="errands", parent=parent["uuid"])

    await task_svc.create_task(
        session, title="Parent tagged", notes=None, status=0, schedule=0, type=0,
        area_uuid=None, project_uuid=None, heading_uuid=None,
        deadline=None, start_date=None, tags=[parent["uuid"]],
    )
    await task_svc.create_task(
        session, title="Child tagged", notes=None, status=0, schedule=0, type=0,
        area_uuid=None, project_uuid=None, heading_uuid=None,
        deadline=None, start_date=None, tags=[child["uuid"]],
    )

    # include_descendants=True (default)
    result = await task_svc.list_tasks(session, tag="work")
    assert len(result) == 2

    # include_descendants=False
    result = await task_svc.list_tasks(session, tag="work", include_descendants=False)
    assert len(result) == 1
    assert result[0]["title"] == "Parent tagged"


# ============================================================
# Pull Sync — tag_ids Tests
# ============================================================


@pytest.mark.asyncio
async def test_pull_sync_applies_tag_ids(session):
    # Pre-create tags
    session.add(Tag(uuid="tag_work____________", title="work"))
    session.add(Tag(uuid="tag_home____________", title="home"))
    await session.commit()

    client = FakeCloudClient(
        items=[
            {"task_abc______________": {
                "t": 0, "e": "Task6",
                "p": {"tt": "Tagged task", "ss": 0, "tg": ["tag_work____________", "tag_home____________"]},
            }},
        ],
        new_index=1,
    )
    await pull_sync(client, session)

    # Verify task_tag rows
    result = await session.execute(
        select(TaskTag).where(TaskTag.task_uuid == "task_abc______________")
    )
    tag_uuids = {tt.tag_uuid for tt in result.scalars()}
    assert tag_uuids == {"tag_work____________", "tag_home____________"}


@pytest.mark.asyncio
async def test_pull_sync_replaces_tags(session):
    """Second sync with different tag_ids should replace, not append."""
    session.add(Tag(uuid="tag_a_______________", title="a"))
    session.add(Tag(uuid="tag_b_______________", title="b"))
    session.add(Task(uuid="task_replace________", title="Task"))
    session.add(TaskTag(task_uuid="task_replace________", tag_uuid="tag_a_______________"))
    await session.commit()

    client = FakeCloudClient(
        items=[
            {"task_replace________": {
                "t": 1, "e": "Task6",
                "p": {"tg": ["tag_b_______________"]},
            }},
        ],
        new_index=1,
    )
    await pull_sync(client, session)

    result = await session.execute(
        select(TaskTag).where(TaskTag.task_uuid == "task_replace________")
    )
    tag_uuids = [tt.tag_uuid for tt in result.scalars()]
    assert tag_uuids == ["tag_b_______________"]


@pytest.mark.asyncio
async def test_pull_sync_removes_all_tags(session):
    """Empty tg list removes all tags."""
    session.add(Tag(uuid="tag_x_______________", title="x"))
    session.add(Task(uuid="task_clear__________", title="Task"))
    session.add(TaskTag(task_uuid="task_clear__________", tag_uuid="tag_x_______________"))
    await session.commit()

    client = FakeCloudClient(
        items=[
            {"task_clear__________": {
                "t": 1, "e": "Task6",
                "p": {"tg": []},
            }},
        ],
        new_index=1,
    )
    await pull_sync(client, session)

    result = await session.execute(
        select(TaskTag).where(TaskTag.task_uuid == "task_clear__________")
    )
    assert list(result.scalars()) == []


# ============================================================
# Push Sync — tag wire format Tests
# ============================================================


@pytest.mark.asyncio
async def test_push_sync_emits_tg(session):
    """Push sync should include tg field with tag UUIDs."""
    now = time.time()
    session.add(Tag(uuid="tag_push____________", title="push"))
    session.add(Task(
        uuid="task_push____________", title="Push me", status=0, schedule=0,
        pending_push=True, creation_date=now, modification_date=now,
    ))
    session.add(TaskTag(task_uuid="task_push____________", tag_uuid="tag_push____________"))
    await session.commit()

    client = FakeCloudClient(new_index=2)
    counts = await push_sync(client, session)
    assert counts["pushed"] == 1

    # Check the wire format
    task_item = client.committed[0]
    payload = task_item["task_push____________"]["p"]
    assert payload["tg"] == ["tag_push____________"]


@pytest.mark.asyncio
async def test_push_sync_emits_empty_tg(session):
    """Push sync should emit tg=[] for tasks with no tags."""
    now = time.time()
    session.add(Task(
        uuid="task_notag__________", title="No tags", status=0, schedule=0,
        pending_push=True, creation_date=now, modification_date=now,
    ))
    await session.commit()

    client = FakeCloudClient(new_index=2)
    await push_sync(client, session)

    task_item = client.committed[0]
    payload = task_item["task_notag__________"]["p"]
    assert payload["tg"] == []


@pytest.mark.asyncio
async def test_push_sync_tags_before_tasks(session):
    """Tag creates/updates should be pushed before tasks."""
    now = time.time()
    session.add(Tag(
        uuid="tag_new_____________", title="new tag", pending_push=True,
    ))
    session.add(Task(
        uuid="task_after___________", title="After", status=0, schedule=0,
        pending_push=True, creation_date=now, modification_date=now,
    ))
    session.add(TaskTag(task_uuid="task_after___________", tag_uuid="tag_new_____________"))
    await session.commit()

    client = FakeCloudClient(new_index=2)
    counts = await push_sync(client, session)
    assert counts["tags_pushed"] == 1
    assert counts["pushed"] == 1

    # First committed item should be the tag
    first = client.committed[0]
    assert "tag_new_____________" in first
    assert first["tag_new_____________"]["e"] == "Tag4"

    # Second should be the task
    second = client.committed[1]
    assert "task_after___________" in second


@pytest.mark.asyncio
async def test_push_sync_tag_delete_after_tasks(session):
    """Tag deletes should come after task updates."""
    now = time.time()
    session.add(Tag(
        uuid="tag_del_____________", title="dying", pending_delete=True,
    ))
    session.add(Task(
        uuid="task_untag__________", title="Untagged", status=0, schedule=0,
        pending_push=True, creation_date=now, modification_date=now,
    ))
    await session.commit()

    client = FakeCloudClient(new_index=2)
    counts = await push_sync(client, session)
    assert counts["tags_deleted"] == 1

    # Task should come before tag delete
    task_item = client.committed[0]
    assert "task_untag__________" in task_item
    tag_delete = client.committed[1]
    assert "tag_del_____________" in tag_delete
    assert tag_delete["tag_del_____________"]["t"] == 2  # ACTION_DELETED


# ============================================================
# Pull Sync — tag deletion cascades TaskTag
# ============================================================


@pytest.mark.asyncio
async def test_pull_sync_tag_deletion_cascades(session):
    """Deleting a tag via pull sync should remove task_tag associations."""
    session.add(Tag(uuid="tag_dying___________", title="dying"))
    session.add(Task(uuid="task_tagged_________", title="Tagged"))
    session.add(TaskTag(task_uuid="task_tagged_________", tag_uuid="tag_dying___________"))
    await session.commit()

    client = FakeCloudClient(
        items=[
            {"tag_dying___________": {"t": 2, "e": "Tag4", "p": {}}},
        ],
        new_index=1,
    )
    await pull_sync(client, session)

    # Tag should be gone
    result = await session.execute(select(Tag).where(Tag.uuid == "tag_dying___________"))
    assert result.scalar_one_or_none() is None

    # TaskTag should be cleaned up
    result = await session.execute(
        select(TaskTag).where(TaskTag.tag_uuid == "tag_dying___________")
    )
    assert list(result.scalars()) == []


# ============================================================
# API Tag Tests
# ============================================================

import things_api.config


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
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": "a" * 32},
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_api_create_tag(authed_client):
    resp = await authed_client.post("/api/tags", json={"title": "work"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "work"
    assert data["uuid"]


@pytest.mark.asyncio
async def test_api_update_tag(authed_client):
    resp = await authed_client.post("/api/tags", json={"title": "old"})
    uuid = resp.json()["uuid"]
    resp = await authed_client.patch(f"/api/tags/{uuid}", json={"title": "new"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "new"


@pytest.mark.asyncio
async def test_api_delete_tag(authed_client):
    resp = await authed_client.post("/api/tags", json={"title": "temp"})
    uuid = resp.json()["uuid"]
    resp = await authed_client.delete(f"/api/tags/{uuid}")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_api_delete_tag_not_found(authed_client):
    resp = await authed_client.delete("/api/tags/nonexistent_tag_id___")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_api_create_task_with_tags(authed_client):
    # Create a tag first
    tag_resp = await authed_client.post("/api/tags", json={"title": "api-tag"})
    tag_uuid = tag_resp.json()["uuid"]

    resp = await authed_client.post("/api/tasks", json={
        "title": "Tagged via API",
        "tags": [tag_uuid],
    })
    assert resp.status_code == 201
    data = resp.json()
    assert len(data["tags"]) == 1
    assert data["tags"][0]["title"] == "api-tag"


@pytest.mark.asyncio
async def test_api_update_task_tags(authed_client):
    tag_resp = await authed_client.post("/api/tags", json={"title": "tag1"})
    tag1_uuid = tag_resp.json()["uuid"]
    tag_resp = await authed_client.post("/api/tags", json={"title": "tag2"})
    tag2_uuid = tag_resp.json()["uuid"]

    task_resp = await authed_client.post("/api/tasks", json={
        "title": "Update tags",
        "tags": [tag1_uuid],
    })
    task_uuid = task_resp.json()["uuid"]

    resp = await authed_client.patch(f"/api/tasks/{task_uuid}", json={
        "tags": [tag2_uuid],
    })
    assert resp.status_code == 200
    assert resp.json()["tags"][0]["uuid"] == tag2_uuid


@pytest.mark.asyncio
async def test_api_list_tasks_by_tag(authed_client):
    tag_resp = await authed_client.post("/api/tags", json={"title": "filter-tag"})
    tag_uuid = tag_resp.json()["uuid"]

    await authed_client.post("/api/tasks", json={
        "title": "Tagged",
        "tags": [tag_uuid],
    })
    await authed_client.post("/api/tasks", json={"title": "Untagged"})

    resp = await authed_client.get(f"/api/tasks/by-tag/{tag_uuid}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "Tagged"


@pytest.mark.asyncio
async def test_api_task_response_includes_tags(authed_client):
    """All task responses should include the tags field."""
    resp = await authed_client.post("/api/tasks", json={"title": "No tags"})
    assert resp.status_code == 201
    assert resp.json()["tags"] == []
