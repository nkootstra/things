"""Tests for database models — exercised through SQLAlchemy async session."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine



@pytest.fixture
async def session():
    """In-memory SQLite async session for testing."""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)

    from things_api.db.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as s:
        yield s

    await engine.dispose()


@pytest.mark.asyncio
async def test_create_and_query_task(session):
    from things_api.db.models import Task

    task = Task(uuid="abc123def456ghi789jk", title="Buy milk", status=0, schedule=0)
    session.add(task)
    await session.commit()

    result = await session.execute(select(Task).where(Task.uuid == "abc123def456ghi789jk"))
    loaded = result.scalar_one()

    assert loaded.title == "Buy milk"
    assert loaded.status == 0
    assert loaded.schedule == 0
    assert loaded.type == 0  # default: task (not project)


@pytest.mark.asyncio
async def test_project_is_task_with_type_1(session):
    from things_api.db.models import Task

    project = Task(uuid="proj_1234567890abcde", title="My Project", type=1)
    session.add(project)
    await session.commit()

    result = await session.execute(select(Task).where(Task.uuid == "proj_1234567890abcde"))
    loaded = result.scalar_one()
    assert loaded.type == 1
    assert loaded.title == "My Project"


@pytest.mark.asyncio
async def test_task_area_relationship(session):
    from things_api.db.models import Area, Task

    area = Area(uuid="area_123456789abcdef", title="Work")
    session.add(area)
    await session.flush()

    task = Task(uuid="task_123456789abcdef", title="Do thing", area_uuid="area_123456789abcdef")
    session.add(task)
    await session.commit()

    result = await session.execute(select(Task).where(Task.uuid == "task_123456789abcdef"))
    loaded = result.scalar_one()
    assert loaded.area_uuid == "area_123456789abcdef"


@pytest.mark.asyncio
async def test_checklist_item_belongs_to_task(session):
    from things_api.db.models import ChecklistItem, Task

    task = Task(uuid="task_cl_123456789abcd", title="Shopping")
    session.add(task)
    await session.flush()

    item = ChecklistItem(uuid="cl_item_12345678abcde", title="Eggs", task_uuid=task.uuid)
    session.add(item)
    await session.commit()

    result = await session.execute(
        select(ChecklistItem).where(ChecklistItem.task_uuid == task.uuid)
    )
    items = result.scalars().all()
    assert len(items) == 1
    assert items[0].title == "Eggs"


@pytest.mark.asyncio
async def test_sync_state_tracks_cursor(session):
    from things_api.db.models import SyncState

    state = SyncState(id=1, history_key="abc123", head_index=42, sync_status="synced")
    session.add(state)
    await session.commit()

    result = await session.execute(select(SyncState).where(SyncState.id == 1))
    loaded = result.scalar_one()
    assert loaded.history_key == "abc123"
    assert loaded.head_index == 42
    assert loaded.sync_status == "synced"
