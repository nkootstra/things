from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse

import things_api.config as config
from things_api.db import engine as engine_mod
from things_api.services.health_service import HealthService
from things_api.services.scheduler_leadership import SchedulerLeadershipService
from things_api.services.scheduler_runtime import SchedulerRuntimeController


logger = logging.getLogger(__name__)

scheduler_runtime: SchedulerRuntimeController | None = None


def _make_sync_fns():
    """Create pull/push functions bound to a fresh session + client."""
    from things_api.cloud.client import ThingsCloudClient
    from things_api.cloud.sync import pull_sync, push_sync
    from things_api.db.engine import async_session

    async def pull():
        client = ThingsCloudClient(email=config.settings.things_email, password=config.settings.things_password)
        try:
            async with async_session() as session:
                return await pull_sync(client, session)
        finally:
            await client.close()

    async def push():
        client = ThingsCloudClient(email=config.settings.things_email, password=config.settings.things_password)
        try:
            async with async_session() as session:
                return await push_sync(client, session)
        finally:
            await client.close()

    return pull, push


def _get_scheduler_leadership_service() -> SchedulerLeadershipService:
    return SchedulerLeadershipService(session_factory=engine_mod.async_session, settings=config.settings)


async def _try_acquire_scheduler_lock(owner_id: str) -> bool:
    return await _get_scheduler_leadership_service().try_acquire(owner_id)


async def _renew_scheduler_lock(owner_id: str) -> bool:
    return await _get_scheduler_leadership_service().renew(owner_id)


async def _release_scheduler_lock(owner_id: str) -> None:
    await _get_scheduler_leadership_service().release(owner_id)


def _default_scheduler_factory(*, pull_fn, push_fn, interval_seconds):
    from things_api.cloud.scheduler import SyncScheduler

    return SyncScheduler(pull_fn=pull_fn, push_fn=push_fn, interval_seconds=interval_seconds)


def _get_scheduler_runtime() -> SchedulerRuntimeController:
    global scheduler_runtime
    if scheduler_runtime is None:
        scheduler_runtime = SchedulerRuntimeController(
            settings=config.settings,
            acquire_lock=_try_acquire_scheduler_lock,
            renew_lock=_renew_scheduler_lock,
            release_lock=_release_scheduler_lock,
            make_sync_fns=_make_sync_fns,
            scheduler_factory=_default_scheduler_factory,
            logger=logger,
        )
    return scheduler_runtime


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global scheduler_runtime
    config.settings.validate_api_key()
    await engine_mod.init_db()

    await _get_scheduler_runtime().start_if_enabled()

    yield

    if scheduler_runtime is not None:
        await scheduler_runtime.stop()
    scheduler_runtime = None


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


def _get_health_service() -> HealthService:
    return HealthService(engine=engine_mod.engine, session_factory=engine_mod.async_session, settings=config.settings)


@app.get("/ready")
async def ready():
    status_code, payload = await _get_health_service().ready_response()
    if status_code == 200:
        return payload
    return JSONResponse(status_code=status_code, content=payload)
