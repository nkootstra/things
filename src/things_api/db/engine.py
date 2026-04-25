"""API database engine — delegates to SDK and adds FastAPI session dependency."""

from sqlalchemy.ext.asyncio import AsyncSession

from things_api.config import settings
from things_sdk.db.engine import create_engine_and_session, init_db as _sdk_init_db

engine, async_session = create_engine_and_session(settings.database_url)


async def init_db() -> None:
    await _sdk_init_db(engine)


async def get_session() -> AsyncSession:  # type: ignore[misc]
    async with async_session() as session:
        yield session
