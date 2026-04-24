from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from things_api.config import settings
from things_api.db.engine import init_db


scheduler = None


def _make_sync_fns():
    """Create pull/push functions bound to a fresh session + client."""
    from things_api.cloud.client import ThingsCloudClient
    from things_api.cloud.sync import pull_sync, push_sync
    from things_api.db.engine import async_session

    async def pull():
        client = ThingsCloudClient(email=settings.things_email, password=settings.things_password)
        async with async_session() as session:
            return await pull_sync(client, session)

    async def push():
        client = ThingsCloudClient(email=settings.things_email, password=settings.things_password)
        async with async_session() as session:
            return await push_sync(client, session)

    return pull, push


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global scheduler
    settings.validate_api_key()
    await init_db()

    if settings.sync_interval_seconds > 0 and settings.things_email:
        from things_api.cloud.scheduler import SyncScheduler

        pull_fn, push_fn = _make_sync_fns()
        scheduler = SyncScheduler(
            pull_fn=pull_fn,
            push_fn=push_fn,
            interval_seconds=settings.sync_interval_seconds,
        )
        scheduler.start()

    yield

    if scheduler:
        scheduler.stop()


app = FastAPI(
    title="Things API",
    description="RESTful API over Things3 data via Things Cloud sync",
    version="0.1.0",
    lifespan=lifespan,
)


from things_api.api.routes import router as api_router

app.include_router(api_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
