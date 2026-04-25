"""Sync configuration protocol for SDK."""

from __future__ import annotations

from typing import Protocol


class SyncConfig(Protocol):
    sync_retry_attempts: int
    sync_retry_base_seconds: float
    sync_circuit_breaker_failures: int
    sync_circuit_breaker_cooldown_seconds: float
