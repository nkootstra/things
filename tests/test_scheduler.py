"""Tests for background sync scheduler."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from things_api.cloud.scheduler import SyncScheduler


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
    await asyncio.sleep(0.15)
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
    await asyncio.sleep(0.25)
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
