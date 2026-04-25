"""
Example: list all pending tasks using things-sdk.

Usage:
    THINGS_EMAIL=you@example.com THINGS_PASSWORD=secret uv run examples/sdk/list_tasks.py
"""

from __future__ import annotations

import asyncio
import os

from things_sdk import (
    DefaultSyncConfig,
    TaskService,
    ThingsClient,
    configure_sync,
    create_engine_and_session,
    init_db,
    pull_sync,
)


async def main() -> None:
    email = os.environ["THINGS_EMAIL"]
    password = os.environ["THINGS_PASSWORD"]

    engine, session_factory = create_engine_and_session("sqlite+aiosqlite:///data/things.db")
    await init_db(engine)
    configure_sync(DefaultSyncConfig())

    client = ThingsClient(email=email, password=password)
    try:
        async with session_factory() as session:
            result = await pull_sync(client, session)
            print(f"Sync complete: {result}")

        svc = TaskService()
        async with session_factory() as session:
            tasks = await svc.list_tasks(session)

        pending = [t for t in tasks if t["status"] == "pending"]
        print(f"\n{len(pending)} pending tasks:\n")
        for t in pending:
            print(f"  [{t['schedule']:>8}] {t['title']}")
    finally:
        await client.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
