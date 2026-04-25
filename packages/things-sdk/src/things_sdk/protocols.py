"""Protocol definitions for Things SDK."""

from __future__ import annotations

from typing import Protocol


class CloudClientProtocol(Protocol):
    """Contract for a Things Cloud HTTP client."""

    async def authenticate(self) -> str: ...

    async def get_items(self, start_index: int = 0) -> tuple[list[dict], int]: ...

    async def commit(self, items: list[dict], ancestor_index: int) -> int: ...

    async def close(self) -> None: ...


class SyncConfig(Protocol):
    """Configuration knobs consumed by the sync engine."""

    sync_retry_attempts: int
    sync_retry_base_seconds: float
    sync_circuit_breaker_failures: int
    sync_circuit_breaker_cooldown_seconds: float


class DefaultSyncConfig:
    """Ready-to-use default sync configuration with sensible production values."""

    sync_retry_attempts: int = 3
    sync_retry_base_seconds: float = 0.25
    sync_circuit_breaker_failures: int = 3
    sync_circuit_breaker_cooldown_seconds: float = 60.0
