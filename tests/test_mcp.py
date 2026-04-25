"""Tests for the Things MCP server — tool registration and mock invocations."""

import json

import pytest

from things_mcp.client import ThingsAPIClient
from things_mcp.server import mcp


# ============================================================
# Tool Registration Tests
# ============================================================


def test_all_read_tools_registered():
    tool_names = set(mcp._tool_manager._tools.keys())
    expected_read = {
        "list_inbox", "list_today", "list_upcoming", "list_anytime",
        "list_someday", "list_logbook", "list_trash", "get_task",
        "list_areas", "list_tags", "list_projects", "list_tasks_by_tag",
    }
    assert expected_read.issubset(tool_names), f"Missing: {expected_read - tool_names}"


def test_all_write_tools_registered():
    tool_names = set(mcp._tool_manager._tools.keys())
    expected_write = {
        "create_task", "update_task", "complete_task", "cancel_task",
        "delete_task", "schedule_task", "move_to_project", "assign_tags",
        "create_tag", "trigger_sync",
    }
    assert expected_write.issubset(tool_names), f"Missing: {expected_write - tool_names}"


def test_tool_count():
    assert len(mcp._tool_manager._tools) == 22


def test_all_tools_have_descriptions():
    for name, tool in mcp._tool_manager._tools.items():
        assert tool.description, f"Tool '{name}' has no description"


# ============================================================
# Integration Tests (MCP → API → SDK, in-process)
# ============================================================


@pytest.fixture
async def api_app():
    """Spin up things-api with in-memory DB."""
    import importlib
    import os

    os.environ["API_KEY"] = "a" * 32
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"

    import things_api.config
    importlib.reload(things_api.config)

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from things_sdk import Base
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
async def mcp_client(api_app):
    """Create a ThingsAPIClient pointed at the in-process API."""
    import httpx
    from httpx import ASGITransport

    transport = ASGITransport(app=api_app)
    http_client = httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": "a" * 32},
        timeout=30.0,
    )

    client = ThingsAPIClient.__new__(ThingsAPIClient)
    client.base_url = "http://test"
    client.api_key = "a" * 32
    client._client = http_client

    yield client
    await http_client.aclose()


@pytest.mark.asyncio
async def test_integration_create_and_list(mcp_client):
    """Create a task, then verify it appears in inbox."""
    task = await mcp_client.create_task({"title": "Test task", "schedule": "inbox"})
    assert task["title"] == "Test task"

    inbox = await mcp_client.list_inbox()
    assert any(t["uuid"] == task["uuid"] for t in inbox)


@pytest.mark.asyncio
async def test_integration_tag_and_filter(mcp_client):
    """Create a tag, create a tagged task, filter by tag."""
    tag = await mcp_client.create_tag({"title": "test-tag"})
    task = await mcp_client.create_task({
        "title": "Tagged task",
        "tags": [tag["uuid"]],
    })
    assert len(task["tags"]) == 1

    by_tag = await mcp_client.list_tasks_by_tag(tag["uuid"])
    assert len(by_tag) == 1
    assert by_tag[0]["uuid"] == task["uuid"]


@pytest.mark.asyncio
async def test_integration_complete_task(mcp_client):
    """Complete a task and verify it moves to logbook."""
    task = await mcp_client.create_task({"title": "Finish me"})
    updated = await mcp_client.update_task(task["uuid"], {"status": "completed"})
    assert updated["status"] == "completed"


@pytest.mark.asyncio
async def test_integration_delete_task(mcp_client):
    """Delete a task and verify it appears in trash."""
    task = await mcp_client.create_task({"title": "Delete me"})
    await mcp_client.delete_task(task["uuid"])

    trash = await mcp_client.list_trash()
    assert any(t["uuid"] == task["uuid"] for t in trash)


@pytest.mark.asyncio
async def test_integration_list_areas(mcp_client):
    """list_areas should return a list (possibly empty)."""
    areas = await mcp_client.list_areas()
    assert isinstance(areas, list)


@pytest.mark.asyncio
async def test_integration_list_tags(mcp_client):
    """list_tags should return created tags."""
    await mcp_client.create_tag({"title": "tag-a"})
    tags = await mcp_client.list_tags()
    assert any(t["title"] == "tag-a" for t in tags)


@pytest.mark.asyncio
async def test_integration_list_projects(mcp_client):
    """list_projects returns type=project tasks."""
    await mcp_client.create_task({"title": "My Project", "type": "project"})
    projects = await mcp_client.list_projects()
    assert any(p["title"] == "My Project" for p in projects)
