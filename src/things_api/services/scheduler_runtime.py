"""Scheduler runtime orchestration with leadership lock heartbeat."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any


class SchedulerRuntimeController:
    def __init__(
        self,
        *,
        settings,
        acquire_lock: Callable[[str], Awaitable[bool]],
        renew_lock: Callable[[str], Awaitable[bool]],
        release_lock: Callable[[str], Awaitable[None]],
        make_sync_fns: Callable[[], tuple[Callable[[], Awaitable[dict]], Callable[[], Awaitable[dict]]]],
        scheduler_factory: Callable[..., Any],
        logger: logging.Logger,
    ) -> None:
        self._settings = settings
        self._acquire_lock = acquire_lock
        self._renew_lock = renew_lock
        self._release_lock = release_lock
        self._make_sync_fns = make_sync_fns
        self._scheduler_factory = scheduler_factory
        self._logger = logger

        self._scheduler: Any | None = None
        self._lock_task: asyncio.Task | None = None
        self._owner_id: str | None = None

    async def start_if_enabled(self) -> None:
        if not (
            self._settings.enable_scheduler
            and self._settings.sync_interval_seconds > 0
            and self._settings.things_email
        ):
            return

        owner_id = uuid.uuid4().hex
        acquired = await self._acquire_lock(owner_id)
        if not acquired:
            self._logger.info("Scheduler lock not acquired; background scheduler disabled for this process")
            return

        pull_fn, push_fn = self._make_sync_fns()
        scheduler = self._scheduler_factory(
            pull_fn=pull_fn,
            push_fn=push_fn,
            interval_seconds=self._settings.sync_interval_seconds,
        )
        scheduler.start()
        self._scheduler = scheduler
        self._owner_id = owner_id
        self._lock_task = asyncio.create_task(self._heartbeat(owner_id))

    async def _heartbeat(self, owner_id: str) -> None:
        while True:
            await asyncio.sleep(max(1.0, self._settings.scheduler_heartbeat_seconds))
            renewed = await self._renew_lock(owner_id)
            if not renewed:
                self._logger.warning("Lost scheduler lock for owner %s; stopping scheduler", owner_id)
                if self._scheduler:
                    self._scheduler.stop()
                self._scheduler = None
                self._owner_id = None
                return

    async def stop(self) -> None:
        if self._lock_task and not self._lock_task.done():
            self._lock_task.cancel()

        if self._scheduler:
            self._scheduler.stop()

        if self._owner_id:
            await self._release_lock(self._owner_id)

        self._scheduler = None
        self._lock_task = None
        self._owner_id = None
