"""Background sync scheduler — runs pull + push on a configurable interval."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


class SyncScheduler:
    def __init__(
        self,
        pull_fn: Callable[[], Awaitable[dict]],
        push_fn: Callable[[], Awaitable[dict]],
        interval_seconds: float = 60,
    ):
        self._pull_fn = pull_fn
        self._push_fn = push_fn
        self._interval = interval_seconds
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._interval <= 0:
            logger.info("Sync scheduler disabled (interval=0)")
            return
        self._task = asyncio.create_task(self._loop())
        logger.info("Sync scheduler started (interval=%ss)", self._interval)

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            logger.info("Sync scheduler stopped")

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._interval)
                await self._run_cycle()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Sync cycle failed, will retry next interval")

    async def _run_cycle(self) -> None:
        pull_result = await self._pull_fn()
        logger.info("Pull sync: %s", pull_result)

        push_result = await self._push_fn()
        logger.info("Push sync: %s", push_result)
