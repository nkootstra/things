"""Tests for smart-list views — SDK methods and API endpoints."""

import time
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from things_sdk import Base, Task, TaskService


# --- Helpers ---


def _epoch(dt: datetime) -> float:
    return dt.timestamp()


def _today_start() -> float:
    now = datetime.now(tz=UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def _days_ago(n: int) -> float:
    return _epoch(datetime.now(tz=UTC) - timedelta(days=n))


def _days_ahead(n: int) -> float:
    return _epoch(datetime.now(tz=UTC) + timedelta(days=n))


# --- SDK Fixtures ---


@pytest.fixture
async def sdk_session():
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


@pytest.fixture
async def seeded_session(sdk_session):
    """Seed the DB with tasks covering all smart-list views."""
    now = time.time()
    tasks = [
        # Inbox: schedule=0, status=0, trashed=False, type=0
        Task(uuid="inbox_task_1_______", title="Inbox 1", schedule=0, status=0, trashed=False, type=0, index=2, creation_date=now, modification_date=now),
        Task(uuid="inbox_task_2_______", title="Inbox 2", schedule=0, status=0, trashed=False, type=0, index=1, creation_date=now, modification_date=now),
        # Inbox project (type=1) — should NOT appear in inbox
        Task(uuid="inbox_project______", title="Inbox Project", schedule=0, status=0, trashed=False, type=1, index=0, creation_date=now, modification_date=now),
        # Today: status=0, start_date <= today, trashed=False
        Task(uuid="today_task_1_______", title="Today 1", status=0, start_date=_today_start(), trashed=False, schedule=1, index=1, today_index=2, creation_date=now, modification_date=now),
        Task(uuid="today_task_2_______", title="Today 2", status=0, start_date=_days_ago(1), trashed=False, schedule=1, index=2, today_index=1, creation_date=now, modification_date=now),
        # Upcoming: status=0, start_date > today, trashed=False
        Task(uuid="upcoming_1_________", title="Upcoming 1", status=0, start_date=_days_ahead(3), deadline=_days_ahead(5), trashed=False, schedule=1, index=0, creation_date=now, modification_date=now),
        Task(uuid="upcoming_2_________", title="Upcoming 2", status=0, start_date=_days_ahead(1), deadline=_days_ahead(2), trashed=False, schedule=1, index=0, creation_date=now, modification_date=now),
        # Anytime: schedule=1, status=0, trashed=False
        Task(uuid="anytime_1__________", title="Anytime 1", schedule=1, status=0, trashed=False, index=2, creation_date=now, modification_date=now),
        Task(uuid="anytime_2__________", title="Anytime 2", schedule=1, status=0, trashed=False, index=1, creation_date=now, modification_date=now),
        # Someday: schedule=2, status=0, trashed=False
        Task(uuid="someday_1__________", title="Someday 1", schedule=2, status=0, trashed=False, index=2, creation_date=now, modification_date=now),
        Task(uuid="someday_2__________", title="Someday 2", schedule=2, status=0, trashed=False, index=1, creation_date=now, modification_date=now),
        # Logbook: status=3, trashed=False
        Task(uuid="logbook_recent_____", title="Done Recently", status=3, trashed=False, completion_date=_days_ago(5), creation_date=now, modification_date=now),
        Task(uuid="logbook_old________", title="Done Long Ago", status=3, trashed=False, completion_date=_days_ago(60), creation_date=now, modification_date=now),
        # Trash
        Task(uuid="trash_1____________", title="Trashed 1", trashed=True, modification_date=_days_ago(1), creation_date=now),
        Task(uuid="trash_2____________", title="Trashed 2", trashed=True, modification_date=now, creation_date=now),
    ]
    for t in tasks:
        sdk_session.add(t)
    await sdk_session.commit()
    return sdk_session


# ============================================================
# SDK Tests
# ============================================================


@pytest.mark.asyncio
async def test_list_inbox(seeded_session, svc):
    result = await svc.list_inbox(seeded_session)
    titles = [t["title"] for t in result]
    assert titles == ["Inbox 2", "Inbox 1"]  # ordered by index ASC
    # Projects excluded
    assert "Inbox Project" not in titles


@pytest.mark.asyncio
async def test_list_today(seeded_session, svc):
    result = await svc.list_today(seeded_session)
    titles = [t["title"] for t in result]
    # Ordered by today_index ASC, then index ASC
    assert titles == ["Today 2", "Today 1"]


@pytest.mark.asyncio
async def test_list_upcoming(seeded_session, svc):
    result = await svc.list_upcoming(seeded_session)
    titles = [t["title"] for t in result]
    # Ordered by start_date ASC
    assert titles == ["Upcoming 2", "Upcoming 1"]


@pytest.mark.asyncio
async def test_list_anytime(seeded_session, svc):
    result = await svc.list_anytime(seeded_session)
    titles = [t["title"] for t in result]
    # schedule=1 tasks ordered by index ASC — includes today/upcoming tasks that also have schedule=1
    assert "Anytime 1" in titles
    assert "Anytime 2" in titles
    # Verify ordering: index ASC
    indices = [t["index"] for t in result]
    assert indices == sorted(indices)


@pytest.mark.asyncio
async def test_list_someday(seeded_session, svc):
    result = await svc.list_someday(seeded_session)
    titles = [t["title"] for t in result]
    assert titles == ["Someday 2", "Someday 1"]  # index ASC


@pytest.mark.asyncio
async def test_list_logbook_default_window(seeded_session, svc):
    result = await svc.list_logbook(seeded_session)
    titles = [t["title"] for t in result]
    # Only recent (within 30 days), ordered by completion_date DESC
    assert titles == ["Done Recently"]
    assert "Done Long Ago" not in titles


@pytest.mark.asyncio
async def test_list_logbook_custom_since(seeded_session, svc):
    result = await svc.list_logbook(seeded_session, since=_days_ago(90))
    titles = [t["title"] for t in result]
    assert "Done Recently" in titles
    assert "Done Long Ago" in titles


@pytest.mark.asyncio
async def test_list_trash(seeded_session, svc):
    result = await svc.list_trash(seeded_session)
    titles = [t["title"] for t in result]
    # Ordered by modification_date DESC
    assert titles == ["Trashed 2", "Trashed 1"]


@pytest.mark.asyncio
async def test_inbox_excludes_trashed(sdk_session, svc):
    """Trashed inbox-eligible tasks must not appear."""
    sdk_session.add(Task(uuid="trashed_inbox______", title="Trashed Inbox", schedule=0, status=0, trashed=True, type=0))
    await sdk_session.commit()
    result = await svc.list_inbox(sdk_session)
    assert all(t["title"] != "Trashed Inbox" for t in result)


@pytest.mark.asyncio
async def test_today_excludes_completed(sdk_session, svc):
    """Completed tasks must not appear in today."""
    sdk_session.add(Task(uuid="completed_today____", title="Done Today", status=3, start_date=_today_start(), trashed=False, schedule=1))
    await sdk_session.commit()
    result = await svc.list_today(sdk_session)
    assert all(t["title"] != "Done Today" for t in result)


# --- Pagination ---


@pytest.mark.asyncio
async def test_inbox_pagination(seeded_session, svc):
    page1 = await svc.list_inbox(seeded_session, limit=1, offset=0)
    page2 = await svc.list_inbox(seeded_session, limit=1, offset=1)
    assert len(page1) == 1
    assert len(page2) == 1
    assert page1[0]["title"] != page2[0]["title"]


@pytest.mark.asyncio
async def test_logbook_default_limit(seeded_session, svc):
    """Logbook defaults to limit=100."""
    result = await svc.list_logbook(seeded_session)
    # Just verify it works with the default — we don't have 100+ items
    assert isinstance(result, list)


# ============================================================
# API Tests
# ============================================================

import os

import things_api.config


@pytest.fixture(autouse=True)
def set_api_key(monkeypatch):
    monkeypatch.setenv("API_KEY", "a" * 32)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite://")


@pytest.fixture
async def api_app():
    """Create app with a fresh in-memory DB, seeded with smart-list data."""
    import importlib

    importlib.reload(things_api.config)

    from things_api.db import engine as engine_mod

    test_engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed data
    now = time.time()
    async with factory() as session:
        tasks = [
            Task(uuid="inbox_task_1_______", title="Inbox 1", schedule=0, status=0, trashed=False, type=0, index=2, creation_date=now, modification_date=now),
            Task(uuid="inbox_task_2_______", title="Inbox 2", schedule=0, status=0, trashed=False, type=0, index=1, creation_date=now, modification_date=now),
            Task(uuid="inbox_project______", title="Inbox Project", schedule=0, status=0, trashed=False, type=1, index=0, creation_date=now, modification_date=now),
            Task(uuid="today_task_1_______", title="Today 1", status=0, start_date=_today_start(), trashed=False, schedule=1, index=1, today_index=2, creation_date=now, modification_date=now),
            Task(uuid="today_task_2_______", title="Today 2", status=0, start_date=_days_ago(1), trashed=False, schedule=1, index=2, today_index=1, creation_date=now, modification_date=now),
            Task(uuid="upcoming_1_________", title="Upcoming 1", status=0, start_date=_days_ahead(3), deadline=_days_ahead(5), trashed=False, schedule=1, index=0, creation_date=now, modification_date=now),
            Task(uuid="upcoming_2_________", title="Upcoming 2", status=0, start_date=_days_ahead(1), deadline=_days_ahead(2), trashed=False, schedule=1, index=0, creation_date=now, modification_date=now),
            Task(uuid="anytime_1__________", title="Anytime 1", schedule=1, status=0, trashed=False, index=2, creation_date=now, modification_date=now),
            Task(uuid="anytime_2__________", title="Anytime 2", schedule=1, status=0, trashed=False, index=1, creation_date=now, modification_date=now),
            Task(uuid="someday_1__________", title="Someday 1", schedule=2, status=0, trashed=False, index=2, creation_date=now, modification_date=now),
            Task(uuid="someday_2__________", title="Someday 2", schedule=2, status=0, trashed=False, index=1, creation_date=now, modification_date=now),
            Task(uuid="logbook_recent_____", title="Done Recently", status=3, trashed=False, completion_date=_days_ago(5), creation_date=now, modification_date=now),
            Task(uuid="logbook_old________", title="Done Long Ago", status=3, trashed=False, completion_date=_days_ago(60), creation_date=now, modification_date=now),
            Task(uuid="trash_1____________", title="Trashed 1", trashed=True, modification_date=_days_ago(1), creation_date=now),
            Task(uuid="trash_2____________", title="Trashed 2", trashed=True, modification_date=now, creation_date=now),
        ]
        for t in tasks:
            session.add(t)
        await session.commit()

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
async def test_api_inbox(authed_client):
    resp = await authed_client.get("/api/tasks/inbox")
    assert resp.status_code == 200
    data = resp.json()
    titles = [t["title"] for t in data]
    assert "Inbox 1" in titles
    assert "Inbox Project" not in titles


@pytest.mark.asyncio
async def test_api_today(authed_client):
    resp = await authed_client.get("/api/tasks/today")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_api_upcoming(authed_client):
    resp = await authed_client.get("/api/tasks/upcoming")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_api_anytime(authed_client):
    resp = await authed_client.get("/api/tasks/anytime")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_api_someday(authed_client):
    resp = await authed_client.get("/api/tasks/someday")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_api_logbook(authed_client):
    resp = await authed_client.get("/api/tasks/logbook")
    assert resp.status_code == 200
    data = resp.json()
    titles = [t["title"] for t in data]
    assert "Done Recently" in titles


@pytest.mark.asyncio
async def test_api_logbook_since(authed_client):
    resp = await authed_client.get("/api/tasks/logbook", params={"since": _days_ago(90)})
    assert resp.status_code == 200
    data = resp.json()
    titles = [t["title"] for t in data]
    assert "Done Long Ago" in titles


@pytest.mark.asyncio
async def test_api_trash(authed_client):
    resp = await authed_client.get("/api/tasks/trash")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 2


@pytest.mark.asyncio
async def test_api_pagination(authed_client):
    resp = await authed_client.get("/api/tasks/inbox", params={"limit": 1})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


@pytest.mark.asyncio
async def test_api_uuid_route_still_works(authed_client):
    """Ensure the {uuid} route isn't shadowed by smart-list routes."""
    resp = await authed_client.get("/api/tasks/inbox_task_1_______")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Inbox 1"
