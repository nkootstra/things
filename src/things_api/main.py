from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from things_api.config import settings
from things_api.db.engine import init_db


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings.validate_api_key()
    await init_db()
    yield


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
