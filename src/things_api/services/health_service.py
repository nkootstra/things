"""Health/readiness service."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from sqlalchemy import select, text

from things_sdk import SyncState

logger = logging.getLogger(__name__)


class HealthService:
    def __init__(self, *, engine, session_factory: Callable, settings) -> None:
        self._engine = engine
        self._session_factory = session_factory
        self._settings = settings

    async def ready_response(self) -> tuple[int, dict]:
        try:
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:
            # Don't leak exception detail (paths, driver internals) to unauth'd callers.
            logger.exception("Readiness probe failed: DB connection error")
            return 503, {"status": "not_ready", "db": "error"}

        try:
            async with self._session_factory() as session:
                result = await session.execute(select(SyncState).where(SyncState.id == 1))
                state = result.scalar_one_or_none()
        except Exception:
            logger.exception("Readiness probe failed: sync_state query error")
            return 503, {"status": "degraded", "db": "ok", "reason": "sync_state_unavailable"}

        if state and (state.sync_errors_total or 0) > self._settings.readiness_max_sync_errors:
            return 503, {
                "status": "degraded",
                "db": "ok",
                "reason": "sync_errors_threshold_exceeded",
                "sync_errors_total": state.sync_errors_total or 0,
            }

        if state and state.circuit_open_until and state.circuit_open_until > time.time():
            return 503, {"status": "degraded", "db": "ok", "reason": "sync_circuit_open"}

        return 200, {"status": "ready", "db": "ok"}
