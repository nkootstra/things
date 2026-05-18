"""Direct unit tests for the shared manual+scheduler sync mutex.

The CAS atomicity comes from ``UPDATE ... WHERE manual_sync_lock_until IS NULL
OR <= now`` — once one session commits a non-null lock, any other session's
identical UPDATE will match zero rows. We test that contract sequentially:
SQLite serializes writers anyway, so simulating "concurrent" callers via
``asyncio.gather`` would only validate SQLite's lock implementation, not ours.
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from things_api.db.models import Base, SyncState
from things_api.services import sync_mutex


@pytest.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        session.add(SyncState(id=1))
        await session.commit()

    yield session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_try_acquire_returns_true_when_unlocked(factory):
    async with factory() as session:
        assert await sync_mutex.try_acquire_sync_lock(session, lock_seconds=30) is True


@pytest.mark.asyncio
async def test_try_acquire_returns_false_when_lock_held(factory):
    """The key CAS invariant: a second acquire fails while the first is held.

    This is what protects manual sync + background scheduler from running
    concurrent commits against the same head_index.
    """
    async with factory() as winner:
        assert await sync_mutex.try_acquire_sync_lock(winner, lock_seconds=30) is True

    async with factory() as loser:
        assert await sync_mutex.try_acquire_sync_lock(loser, lock_seconds=30) is False


@pytest.mark.asyncio
async def test_try_acquire_succeeds_after_lock_expires(factory):
    async with factory() as session:
        # Acquire with a 0-clamped-to-1s lock, then force-expire it.
        assert await sync_mutex.try_acquire_sync_lock(session, lock_seconds=1) is True

        from sqlalchemy import update

        await session.execute(
            update(SyncState).where(SyncState.id == 1).values(manual_sync_lock_until=time.time() - 1)
        )
        await session.commit()

        assert await sync_mutex.try_acquire_sync_lock(session, lock_seconds=30) is True


@pytest.mark.asyncio
async def test_sync_lock_releases_on_normal_exit(factory):
    async with factory() as session:
        async with sync_mutex.sync_lock(session, lock_seconds=30) as acquired:
            assert acquired is True

    async with factory() as fresh:
        assert await sync_mutex.try_acquire_sync_lock(fresh, lock_seconds=30) is True


@pytest.mark.asyncio
async def test_sync_lock_releases_on_exception(factory):
    with pytest.raises(RuntimeError, match="boom"):
        async with factory() as session:
            async with sync_mutex.sync_lock(session, lock_seconds=30) as acquired:
                assert acquired is True
                raise RuntimeError("boom")

    async with factory() as fresh:
        assert await sync_mutex.try_acquire_sync_lock(fresh, lock_seconds=30) is True


@pytest.mark.asyncio
async def test_sync_lock_body_exception_wins_over_release_failure(factory, monkeypatch):
    """If both body and release_sync_lock raise, the body exception must
    propagate — release failures must not mask the real error."""

    async def fake_release(_session):
        raise RuntimeError("release-failed (should be swallowed)")

    monkeypatch.setattr(sync_mutex, "release_sync_lock", fake_release)

    with pytest.raises(ValueError, match="real-error"):
        async with factory() as session:
            async with sync_mutex.sync_lock(session, lock_seconds=30):
                raise ValueError("real-error")


@pytest.mark.asyncio
async def test_sync_lock_yields_false_when_already_held(factory):
    async with factory() as holder:
        assert await sync_mutex.try_acquire_sync_lock(holder, lock_seconds=30) is True

    async with factory() as contender:
        async with sync_mutex.sync_lock(contender, lock_seconds=30) as acquired:
            assert acquired is False
