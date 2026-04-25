"""Optional observability: structured JSON logging and a lightweight metrics endpoint."""

from __future__ import annotations

import json
import logging
import time


class _JsonFormatter(logging.Formatter):
    """Minimal stdlib JSON log formatter — no extra dependencies."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(log_format: str = "text") -> None:
    """Configure logging based on LOG_FORMAT setting.

    - "text" (default): standard human-readable log output
    - "json": structured JSON log output, one record per line
    """
    root = logging.getLogger()
    if root.handlers:
        root.handlers.clear()

    handler = logging.StreamHandler()

    if log_format == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))

    root.addHandler(handler)
    root.setLevel(logging.INFO)
