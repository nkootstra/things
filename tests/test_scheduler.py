"""Tests for background sync scheduler."""

import asyncio
import logging
from unittest.mock import AsyncMock

import pytest

from things_api.cloud.scheduler import SyncScheduler
from things_api.services.scheduler_runtime import SchedulerRuntimeController


@pytest.mark.asyncio
async def test_scheduler_calls_pull_sync_on_interval():
    pull_sync = AsyncMock(return_value={"created": 0, "modified": 0, "deleted": 0, "skipped": 0})
    push_sync = AsyncMock(return_value={"pushed": 0})

    scheduler = SyncScheduler(
        pull_fn=pull_sync,
        push_fn=push_sync,
        interval_seconds=0.05,
    )

    scheduler.start()
    await asyncio.sleep(0.5)
    scheduler.stop()

    assert pull_sync.call_count >= 2
    assert push_sync.call_count >= 2


@pytest.mark.asyncio
async def test_scheduler_does_not_crash_on_sync_error():
    pull_sync = AsyncMock(side_effect=Exception("cloud down"))
    push_sync = AsyncMock(return_value={"pushed": 0})

    scheduler = SyncScheduler(
        pull_fn=pull_sync,
        push_fn=push_sync,
        interval_seconds=0.05,
    )

    scheduler.start()
    await asyncio.sleep(0.5)
    scheduler.stop()

    # Should have retried despite errors
    assert pull_sync.call_count >= 2


@pytest.mark.asyncio
async def test_scheduler_zero_interval_disables():
    pull_sync = AsyncMock()
    push_sync = AsyncMock()

    scheduler = SyncScheduler(
        pull_fn=pull_sync,
        push_fn=push_sync,
        interval_seconds=0,
    )

    scheduler.start()
    await asyncio.sleep(0.1)
    scheduler.stop()

    assert pull_sync.call_count == 0


# --- SchedulerRuntimeController heartbeat ---


class _FakeScheduler:
    def __init__(self):
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class _FakeSettings:
    enable_scheduler = True
    sync_interval_seconds = 60
    things_email = "test@example.com"
    scheduler_heartbeat_seconds = 0.05


def _make_runtime(*, renew_lock, scheduler):
    release_calls: list[str] = []

    async def acquire(_owner):
        return True

    async def release(owner):
        release_calls.append(owner)

    def make_sync_fns():
        return AsyncMock(), AsyncMock()

    def scheduler_factory(*, pull_fn, push_fn, interval_seconds):
        return scheduler

    controller = SchedulerRuntimeController(
        settings=_FakeSettings(),
        acquire_lock=acquire,
        renew_lock=renew_lock,
        release_lock=release,
        make_sync_fns=make_sync_fns,
        scheduler_factory=scheduler_factory,
        logger=logging.getLogger("test"),
    )
    return controller, release_calls


@pytest.mark.asyncio
async def test_heartbeat_stops_scheduler_when_renew_raises():
    """A DB blip during lock renewal must not silently kill the heartbeat
    task: the scheduler should stop defensively so two processes can't
    race for leadership."""
    scheduler = _FakeScheduler()

    async def renew_lock(_owner):
        raise RuntimeError("simulated DB connection reset")

    controller, _ = _make_runtime(renew_lock=renew_lock, scheduler=scheduler)

    await controller.start_if_enabled()
    # Heartbeat sleeps `max(1.0, heartbeat_seconds)` so wait > 1s.
    await asyncio.sleep(1.2)

    assert scheduler.started is True
    assert scheduler.stopped is True
    assert controller._scheduler is None
    assert controller._owner_id is None


@pytest.mark.asyncio
async def test_heartbeat_stops_scheduler_when_renew_returns_false():
    scheduler = _FakeScheduler()
    calls = {"n": 0}

    async def renew_lock(_owner):
        calls["n"] += 1
        return calls["n"] < 2

    controller, _ = _make_runtime(renew_lock=renew_lock, scheduler=scheduler)

    await controller.start_if_enabled()
    await asyncio.sleep(2.3)

    assert scheduler.stopped is True
    assert controller._scheduler is None
