"""Shared mutex for sync cycles.

Both the manual sync endpoint and the background scheduler use the
``SyncState.manual_sync_lock_until`` row as a single, atomic CAS lock so
they cannot run concurrently. Without this, a manual sync triggered
mid-background-cycle could submit overlapping cloud commits, trip the
circuit breaker, or corrupt ``head_index``.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from things_sdk import SyncState


async def try_acquire_sync_lock(session: AsyncSession, *, lock_seconds: float) -> bool:
    """Attempt to acquire the sync lock via atomic CAS.

    Returns True if acquired, False if another caller holds it.
    Caller is responsible for committing the session afterwards (we do not
    commit here so the caller can scope a larger transaction if needed —
    but in practice we commit immediately to make the lock visible).
    """
    now = time.time()
    lock_until = now + max(1.0, lock_seconds)
    stmt = (
        update(SyncState)
        .where(SyncState.id == 1)
        .where(
            or_(
                SyncState.manual_sync_lock_until.is_(None),
                SyncState.manual_sync_lock_until <= now,
            )
        )
        .values(manual_sync_lock_until=lock_until)
    )
    res: CursorResult = await session.execute(stmt)  # type: ignore[assignment]
    await session.commit()
    return bool(res.rowcount)


async def release_sync_lock(session: AsyncSession) -> None:
    """Release the sync lock unconditionally."""
    await session.execute(
        update(SyncState).where(SyncState.id == 1).values(manual_sync_lock_until=None)
    )
    await session.commit()


async def ensure_sync_state(session: AsyncSession) -> SyncState:
    """Ensure the singleton SyncState row exists; return it."""
    result = await session.execute(select(SyncState).where(SyncState.id == 1))
    state = result.scalar_one_or_none()
    if state is None:
        state = SyncState(id=1)
        session.add(state)
        await session.commit()
    return state


@asynccontextmanager
async def sync_lock(
    session: AsyncSession, *, lock_seconds: float
) -> AsyncIterator[bool]:
    """Context manager wrapping CAS acquire + guaranteed release.

    Yields True if the lock was acquired (and will be released on exit),
    False if another holder won the CAS (no release attempted).
    """
    acquired = await try_acquire_sync_lock(session, lock_seconds=lock_seconds)
    try:
        yield acquired
    finally:
        if acquired:
            try:
                await release_sync_lock(session)
            except Exception:
                # The session may already be in an error state; the lock will
                # expire naturally after lock_seconds. Don't mask the original
                # exception by raising here.
                pass
