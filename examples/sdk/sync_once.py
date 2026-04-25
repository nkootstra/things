"""
Example: run a single pull + push sync cycle using things-sdk.

Useful as a cron job or one-shot sync trigger.

Usage:
    THINGS_EMAIL=you@example.com THINGS_PASSWORD=secret uv run examples/sdk/sync_once.py
"""

from __future__ import annotations

import asyncio
import os

from things_sdk import (
    DefaultSyncConfig,
    ThingsClient,
    configure_sync,
    create_engine_and_session,
    init_db,
    pull_sync,
    push_sync,
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
            pull_result = await pull_sync(client, session)
            print(f"Pull:  {pull_result}")

        async with session_factory() as session:
            push_result = await push_sync(client, session)
            print(f"Push:  {push_result}")
    finally:
        await client.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
