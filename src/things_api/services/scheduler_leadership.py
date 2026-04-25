"""Scheduler leadership lock service."""

from __future__ import annotations

from collections.abc import Callable
import time

from sqlalchemy import or_, select, update

from things_sdk import SyncState


class SchedulerLeadershipService:
    def __init__(self, *, session_factory: Callable, settings) -> None:
        self._session_factory = session_factory
        self._settings = settings

    async def try_acquire(self, owner_id: str) -> bool:
        now = time.time()
        lock_until = now + max(1.0, self._settings.scheduler_lock_seconds)

        async with self._session_factory() as session:
            result = await session.execute(select(SyncState).where(SyncState.id == 1))
            state = result.scalar_one_or_none()
            if not state:
                session.add(SyncState(id=1))
                await session.commit()

            stmt = (
                update(SyncState)
                .where(SyncState.id == 1)
                .where(or_(SyncState.scheduler_lock_until.is_(None), SyncState.scheduler_lock_until <= now))
                .values(scheduler_lock_owner=owner_id, scheduler_lock_until=lock_until)
            )
            res = await session.execute(stmt)
            await session.commit()
            return bool(res.rowcount)

    async def renew(self, owner_id: str) -> bool:
        now = time.time()
        lock_until = now + max(1.0, self._settings.scheduler_lock_seconds)
        async with self._session_factory() as session:
            stmt = (
                update(SyncState)
                .where(SyncState.id == 1)
                .where(SyncState.scheduler_lock_owner == owner_id)
                .values(scheduler_lock_until=lock_until)
            )
            res = await session.execute(stmt)
            await session.commit()
            return bool(res.rowcount)

    async def release(self, owner_id: str) -> None:
        async with self._session_factory() as session:
            stmt = (
                update(SyncState)
                .where(SyncState.id == 1)
                .where(SyncState.scheduler_lock_owner == owner_id)
                .values(scheduler_lock_owner=None, scheduler_lock_until=None)
            )
            await session.execute(stmt)
            await session.commit()
