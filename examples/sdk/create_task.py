"""
Example: create a task and push it to Things Cloud using things-sdk.

Usage:
    THINGS_EMAIL=you@example.com THINGS_PASSWORD=secret uv run examples/sdk/create_task.py
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
    push_sync,
)


async def main() -> None:
    email = os.environ["THINGS_EMAIL"]
    password = os.environ["THINGS_PASSWORD"]

    engine, session_factory = create_engine_and_session("sqlite+aiosqlite:///data/things.db")
    await init_db(engine)
    configure_sync(DefaultSyncConfig())

    svc = TaskService()
    client = ThingsClient(email=email, password=password)
    try:
        async with session_factory() as session:
            task = await svc.create_task(
                session,
                title="Created by things-sdk",
                notes="This task was created via the things-sdk Python library.",
                status=0,       # pending
                schedule=1,     # anytime
                type=0,         # task
                area_uuid=None,
                project_uuid=None,
                heading_uuid=None,
                deadline=None,
                start_date=None,
                # tags=["work"],  # optionally assign tags by name or UUID
            )
            print(f"Created locally: {task['uuid']} — {task['title']}")
            print(f"  Tags: {task['tags']}")

        async with session_factory() as session:
            result = await push_sync(client, session)
            print(f"Pushed to cloud: {result}")
    finally:
        await client.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
