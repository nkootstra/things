"""Hardening tests for edge cases found through Things3 reverse engineering."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from things_sdk import Base, Task, configure_sync
from things_sdk.cloud.sync import parse_notes, pull_sync


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


class FakeCloudClient:
    def __init__(self, items=None, new_index=1):
        self.items = items or []
        self.new_index = new_index
    async def authenticate(self): return "key"
    async def get_items(self, start_index=0): return self.items, self.new_index
    async def commit(self, items, ancestor_index): return self.new_index
    async def close(self): pass


# ============================================================
# Notes Parsing — all Things3 formats
# ============================================================


class TestNotesParsing:
    def test_simple_text_format(self):
        """Standard create format: {_t: tx, ch: 0, v: text, t: 1}"""
        assert parse_notes({"_t": "tx", "ch": 0, "v": "Hello world", "t": 1}) == "Hello world"

    def test_empty_text(self):
        assert parse_notes({"_t": "tx", "ch": 0, "v": "", "t": 1}) == ""

    def test_rich_text_with_paragraphs(self):
        """Things3 sends rich text as: {t: 2, ps: [{r: text, ...}], _t: tx}"""
        notes = {"t": 2, "ps": [{"r": "First paragraph\n", "p": 0, "l": 0, "ch": 123}], "_t": "tx"}
        assert parse_notes(notes) == "First paragraph\n"

    def test_multi_paragraph_notes(self):
        notes = {"t": 2, "ps": [
            {"r": "Line 1\n", "p": 0, "l": 0, "ch": 1},
            {"r": "Line 2\n", "p": 0, "l": 0, "ch": 2},
        ], "_t": "tx"}
        assert parse_notes(notes) == "Line 1\nLine 2\n"

    def test_clear_notes_signal(self):
        """Things3 clears notes with: {t: 0, diag: apply, _t: tx}"""
        assert parse_notes({"t": 0, "diag": "apply", "_t": "tx"}) == ""

    def test_none_notes(self):
        assert parse_notes(None) == ""

    def test_empty_dict(self):
        assert parse_notes({}) == ""

    def test_legacy_xml(self):
        assert parse_notes('<note xml:space="preserve">Old note</note>') == "Old note"

    def test_plain_string(self):
        assert parse_notes("Just a string") == "Just a string"


# ============================================================
# Partial Update — explicit null clears fields
# ============================================================


class TestPartialUpdateNulls:
    @pytest.mark.asyncio
    async def test_null_completion_date_clears_it(self, session):
        """Things3 sends {sp: null} to un-complete a task."""
        session.add(Task(uuid="task_uncomplete______", title="Done", status=3, completion_date=1777000000.0))
        await session.commit()

        client = FakeCloudClient(items=[
            {"task_uncomplete______": {"t": 1, "e": "Task6", "p": {"ss": 0, "sp": None, "md": 1777001000.0}}},
        ], new_index=1)
        await pull_sync(client, session)

        result = await session.execute(select(Task).where(Task.uuid == "task_uncomplete______"))
        task = result.scalar_one()
        assert task.status == 0
        assert task.completion_date is None

    @pytest.mark.asyncio
    async def test_null_start_date_clears_it(self, session):
        """Moving task to inbox clears start_date."""
        session.add(Task(uuid="task_clear_sr________", title="Scheduled", start_date=1777161600.0))
        await session.commit()

        client = FakeCloudClient(items=[
            {"task_clear_sr________": {"t": 1, "e": "Task6", "p": {"sr": None, "st": 0, "md": 1777002000.0}}},
        ], new_index=1)
        await pull_sync(client, session)

        result = await session.execute(select(Task).where(Task.uuid == "task_clear_sr________"))
        task = result.scalar_one()
        assert task.start_date is None
        assert task.schedule == 0

    @pytest.mark.asyncio
    async def test_null_deadline_clears_it(self, session):
        session.add(Task(uuid="task_clear_dd________", title="Has deadline", deadline=1777248000.0))
        await session.commit()

        client = FakeCloudClient(items=[
            {"task_clear_dd________": {"t": 1, "e": "Task6", "p": {"dd": None, "md": 1777003000.0}}},
        ], new_index=1)
        await pull_sync(client, session)

        result = await session.execute(select(Task).where(Task.uuid == "task_clear_dd________"))
        task = result.scalar_one()
        assert task.deadline is None


# ============================================================
# Contact field — wire sends int, not list
# ============================================================


class TestContactField:
    @pytest.mark.asyncio
    async def test_contact_as_int_does_not_crash(self, session):
        """Wire sends do:0 (int), not do:['uuid']. Must not crash."""
        client = FakeCloudClient(items=[
            {"task_contact_int_____": {
                "t": 0, "e": "Task6",
                "p": {"tt": "Contact test", "ss": 0, "do": 0},
            }},
        ], new_index=1)
        await pull_sync(client, session)

        result = await session.execute(select(Task).where(Task.uuid == "task_contact_int_____"))
        task = result.scalar_one()
        assert task.title == "Contact test"
        # contact_uuid should remain None (int 0 means no contact)
        assert task.contact_uuid is None

    @pytest.mark.asyncio
    async def test_contact_as_list_still_works(self, session):
        """Legacy format do:['uuid'] should still work."""
        client = FakeCloudClient(items=[
            {"task_contact_list____": {
                "t": 0, "e": "Task6",
                "p": {"tt": "Has contact", "ss": 0, "do": ["contact_uuid_________"]},
            }},
        ], new_index=1)
        await pull_sync(client, session)

        result = await session.execute(select(Task).where(Task.uuid == "task_contact_list____"))
        task = result.scalar_one()
        assert task.contact_uuid == "contact_uuid_________"


# ============================================================
# Partial update — only changed fields
# ============================================================


class TestPartialUpdates:
    @pytest.mark.asyncio
    async def test_partial_update_title_only(self, session):
        """Things3 sends only changed fields in t=1 updates."""
        session.add(Task(
            uuid="task_partial__________", title="Old", notes="Keep me",
            status=0, schedule=1, start_date=1777161600.0,
        ))
        await session.commit()

        client = FakeCloudClient(items=[
            {"task_partial__________": {"t": 1, "e": "Task6", "p": {"tt": "New", "md": 1777005000.0}}},
        ], new_index=1)
        await pull_sync(client, session)

        result = await session.execute(select(Task).where(Task.uuid == "task_partial__________"))
        task = result.scalar_one()
        assert task.title == "New"
        assert task.notes == "Keep me"  # unchanged
        assert task.start_date == 1777161600.0  # unchanged
        assert task.schedule == 1  # unchanged

    @pytest.mark.asyncio
    async def test_partial_update_index_only(self, session):
        """Reorder operations only send ix."""
        session.add(Task(uuid="task_reorder_________", title="Reorder me", index=100))
        await session.commit()

        client = FakeCloudClient(items=[
            {"task_reorder_________": {"t": 1, "e": "Task6", "p": {"ix": -500}}},
        ], new_index=1)
        await pull_sync(client, session)

        result = await session.execute(select(Task).where(Task.uuid == "task_reorder_________"))
        task = result.scalar_one()
        assert task.index == -500
        assert task.title == "Reorder me"  # unchanged
