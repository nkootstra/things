"""Sync service encapsulating sync status and manual sync orchestration."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

import things_sdk.cloud.client as cloud_client_mod
import things_sdk.cloud.sync as cloud_sync_mod
import things_api.config as config
from things_sdk.db.models import SyncState
from things_sdk.protocols import CloudClientProtocol
from things_api.services.contracts import SyncServiceProtocol


class SyncService:
    def __init__(
        self,
        *,
        client_factory: Callable[[str, str], CloudClientProtocol] | None = None,
        pull_fn: Callable[[CloudClientProtocol, AsyncSession], Awaitable[dict]] | None = None,
        push_fn: Callable[[CloudClientProtocol, AsyncSession], Awaitable[dict]] | None = None,
    ) -> None:
        self._client_factory: Callable[[str, str], CloudClientProtocol] = (
            client_factory or cloud_client_mod.ThingsCloudClient
        )
        self._pull_fn: Callable[[CloudClientProtocol, AsyncSession], Awaitable[dict]] = (
            pull_fn or cloud_sync_mod.pull_sync
        )
        self._push_fn: Callable[[CloudClientProtocol, AsyncSession], Awaitable[dict]] = (
            push_fn or cloud_sync_mod.push_sync
        )

    async def get_status(self, session: AsyncSession) -> dict:
        result = await session.execute(select(SyncState).where(SyncState.id == 1))
        state = result.scalar_one_or_none()
        if not state:
            return {
                "sync_status": "never",
                "head_index": 0,
                "last_sync_at": None,
                "last_error": None,
                "last_pull_skipped": 0,
                "sync_errors_total": 0,
                "consecutive_sync_errors": 0,
                "circuit_open_until": None,
                "circuit_probe_active": False,
                "manual_sync_lock_until": None,
            }

        return {
            "sync_status": state.sync_status or "never",
            "head_index": state.head_index,
            "last_sync_at": _ts_to_utc(state.last_sync_at),
            "last_error": state.last_error,
            "last_pull_skipped": state.last_pull_skipped or 0,
            "sync_errors_total": state.sync_errors_total or 0,
            "consecutive_sync_errors": state.consecutive_sync_errors or 0,
            "circuit_open_until": _ts_to_utc(state.circuit_open_until),
            "circuit_probe_active": bool(state.circuit_probe_active),
            "manual_sync_lock_until": _ts_to_utc(state.manual_sync_lock_until),
        }

    async def trigger_manual_sync(self, session: AsyncSession) -> dict:
        if not config.settings.things_email or not config.settings.things_password:
            raise HTTPException(status_code=503, detail="Things Cloud credentials not configured")

        result = await session.execute(select(SyncState).where(SyncState.id == 1))
        state = result.scalar_one_or_none()
        if not state:
            state = SyncState(id=1)
            session.add(state)
            await session.commit()

        if state.last_sync_at:
            elapsed = time.time() - state.last_sync_at
            if elapsed < 60:
                raise HTTPException(status_code=429, detail=f"Rate limited. Try again in {int(60 - elapsed)}s")

        now = time.time()
        lock_until = now + max(1.0, config.settings.manual_sync_lock_seconds)
        lock_stmt = (
            update(SyncState)
            .where(SyncState.id == 1)
            .where(or_(SyncState.manual_sync_lock_until.is_(None), SyncState.manual_sync_lock_until <= now))
            .values(manual_sync_lock_until=lock_until)
        )
        lock_res = await session.execute(lock_stmt)
        await session.commit()
        if not lock_res.rowcount:
            raise HTTPException(status_code=409, detail="Manual sync already in progress")

        client = self._client_factory(config.settings.things_email, config.settings.things_password)
        try:
            pull_result = await self._pull_fn(client, session)
            push_result = await self._push_fn(client, session)
            return {"pull": pull_result, "push": push_result}
        except cloud_sync_mod.SyncCircuitOpenError as e:
            raise HTTPException(status_code=503, detail=f"Circuit breaker open. Retry in {e.retry_after_seconds}s")
        finally:
            await client.close()
            await session.execute(update(SyncState).where(SyncState.id == 1).values(manual_sync_lock_until=None))
            await session.commit()


def get_sync_service() -> SyncServiceProtocol:
    return SyncService()


def _ts_to_utc(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=UTC).isoformat()
