"""In-process sync metrics counters — zero dependencies, opt-in only."""

from __future__ import annotations

from dataclasses import dataclass, field


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
