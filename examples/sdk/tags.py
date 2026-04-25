"""
Example: create and assign tags using things-sdk.

Usage:
    THINGS_EMAIL=you@example.com THINGS_PASSWORD=secret uv run examples/sdk/tags.py
"""

from __future__ import annotations

import asyncio
import os

from things_sdk import (
    DefaultSyncConfig,
    TagService,
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

    tag_svc = TagService()
    task_svc = TaskService()
    client = ThingsClient(email=email, password=password)

    try:
        # Create a tag hierarchy: work/errands
        async with session_factory() as session:
            work = await tag_svc.create_tag(session, title="work")
            errands = await tag_svc.create_tag(session, title="errands", parent=work["uuid"])
            print(f"Created tags: work ({work['uuid']}), work/errands ({errands['uuid']})")

        # Create a task with the tag
        async with session_factory() as session:
            task = await task_svc.create_task(
                session,
                title="Pick up dry cleaning",
                notes="On the way home from the office.",
                status=0,
                schedule=1,  # anytime
                type=0,
                area_uuid=None,
                project_uuid=None,
                heading_uuid=None,
                deadline=None,
                start_date=None,
                tags=["work/errands"],  # resolve by hierarchical name
            )
            print(f"Created task: {task['title']} with tags: {[t['title'] for t in task['tags']]}")

        # Filter tasks by tag
        async with session_factory() as session:
            work_tasks = await task_svc.list_tasks(session, tag="work")
            print(f"\nAll tasks tagged 'work' (including descendants): {len(work_tasks)}")
            for t in work_tasks:
                print(f"  • {t['title']} — tags: {[tag['title'] for tag in t['tags']]}")

        # Push to Things Cloud
        async with session_factory() as session:
            result = await push_sync(client, session)
            print(f"\nPushed: {result}")
    finally:
        await client.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
