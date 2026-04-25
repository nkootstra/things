# Things SDK

Reusable Python SDK for Things Cloud sync.

> Looking for the HTTP service instead of the Python library? See the root [`README.md`](../../README.md) for `things-api`.

## When should I use this?

Use `things-sdk` when you want to build Python-native tooling on top of Things Cloud, such as:
- CLI tools
- automation scripts
- background workers
- MCP servers
- custom internal integrations

If you want a ready-made HTTP/HTTPS service instead, use `things-api` from the repository root.

## Installation

```bash
pip install things-sdk
```

## Quick Start

```python
import asyncio
from things_sdk import (
    ThingsClient,
    TaskService,
    configure_sync,
    create_engine_and_session,
    init_db,
    pull_sync,
    push_sync,
)


class MySyncConfig:
    sync_retry_attempts = 3
    sync_retry_base_seconds = 0.25
    sync_circuit_breaker_failures = 3
    sync_circuit_breaker_cooldown_seconds = 60.0


async def main():
    # 1. Database setup
    engine, session_factory = create_engine_and_session(
        "sqlite+aiosqlite:///data/things.db"
    )
    await init_db(engine)

    # 2. Configure sync engine
    configure_sync(MySyncConfig())

    # 3. Sync from Things Cloud
    client = ThingsClient(email="you@example.com", password="your-password")
    async with session_factory() as session:
        result = await pull_sync(client, session)
        print(f"Pulled: {result}")
    await client.close()

    # 4. Query tasks
    svc = TaskService()
    async with session_factory() as session:
        tasks = await svc.list_tasks(session)
        for t in tasks:
            print(f"  - {t['title']} ({t['status']})")

    await engine.dispose()


asyncio.run(main())
```

## What's included

| Module | Description |
|---|---|
| `ThingsClient` | Async HTTP client for Things Cloud |
| `pull_sync` / `push_sync` | Sync engine with retry + circuit breaker |
| `TaskService` | CRUD operations for tasks, areas, tags |
| `create_engine_and_session` | SQLAlchemy async engine factory |
| Domain models | `Task`, `Area`, `Tag`, `ChecklistItem`, `SyncState` |
| `CloudClientProtocol` | Protocol for custom client implementations |
| `SyncConfig` | Protocol for sync configuration |
| `EntityHandler` | Strategy pattern for extending sync to new entity types |

## Smoke-tested release artifacts

Releases validate that the SDK is not just built, but actually installable and usable:
- build wheel + sdist
- install wheel into a clean virtualenv
- import `things_sdk`
- create a SQLAlchemy engine/session factory
- after publish, install `things-sdk==<version>` from PyPI and repeat the basic checks

That means a published `things-sdk` release has already passed both a build-time smoke test and a post-publish verification in CI.
