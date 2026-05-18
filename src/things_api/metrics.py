"""In-process sync metrics counters — zero dependencies, opt-in only."""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Literal, TypeVar

from things_api.cloud.sync import SyncCircuitOpenError


@dataclass
class SyncMetrics:
    sync_pull_total: int = 0
    sync_push_total: int = 0
    sync_errors_total: int = 0
    circuit_open_total: int = 0

    def record_pull(self) -> None:
        self.sync_pull_total += 1

    def record_push(self) -> None:
        self.sync_push_total += 1

    def record_error(self) -> None:
        self.sync_errors_total += 1

    def record_circuit_open(self) -> None:
        self.circuit_open_total += 1

    def to_prometheus_text(self) -> str:
        lines = [
            "# HELP sync_pull_total Total successful pull sync operations",
            "# TYPE sync_pull_total counter",
            f"sync_pull_total {self.sync_pull_total}",
            "# HELP sync_push_total Total successful push sync operations",
            "# TYPE sync_push_total counter",
            f"sync_push_total {self.sync_push_total}",
            "# HELP sync_errors_total Total sync errors",
            "# TYPE sync_errors_total counter",
            f"sync_errors_total {self.sync_errors_total}",
            "# HELP circuit_open_total Total times circuit breaker opened",
            "# TYPE circuit_open_total counter",
            f"circuit_open_total {self.circuit_open_total}",
        ]
        return "\n".join(lines) + "\n"


# Module-level singleton — only populated when ENABLE_METRICS=true
metrics = SyncMetrics()


T = TypeVar("T")


async def instrument_sync(kind: Literal["pull", "push"], awaitable: Awaitable[T]) -> T:
    """Run a sync coroutine, recording success/error counters.

    Treats SyncCircuitOpenError as an error AND a circuit-open event so the
    /metrics endpoint reflects both signals separately.
    """
    try:
        result = await awaitable
    except SyncCircuitOpenError:
        metrics.record_error()
        metrics.record_circuit_open()
        raise
    except Exception:
        metrics.record_error()
        raise
    if kind == "pull":
        metrics.record_pull()
    else:
        metrics.record_push()
    return result
