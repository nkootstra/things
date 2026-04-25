"""
Example: browse smart lists using things-sdk.

Usage:
    THINGS_EMAIL=you@example.com THINGS_PASSWORD=secret uv run examples/sdk/smart_lists.py
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
            await pull_sync(client, session)

        svc = TaskService()
        async with session_factory() as session:
            print("📥 Inbox:")
            for t in await svc.list_inbox(session):
                print(f"  • {t['title']}")

            print("\n📅 Today:")
            for t in await svc.list_today(session):
                print(f"  • {t['title']}")

            print("\n🔮 Upcoming:")
            for t in await svc.list_upcoming(session):
                print(f"  • {t['title']} (starts: {t['start_date']})")

            print("\n⭐ Anytime:")
            for t in await svc.list_anytime(session, limit=5):
                print(f"  • {t['title']}")

            print("\n💤 Someday:")
            for t in await svc.list_someday(session, limit=5):
                print(f"  • {t['title']}")

            print("\n✅ Logbook (last 7 days):")
            import time
            since = time.time() - 7 * 86400
            for t in await svc.list_logbook(session, since=since, limit=5):
                print(f"  • {t['title']} (completed: {t['completion_date']})")
    finally:
        await client.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
