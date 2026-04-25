from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def _ensure_sqlite_directory(database_url: str) -> None:
    prefix = "sqlite+aiosqlite:///"
    if not database_url.startswith(prefix):
        return
    db_path = database_url[len(prefix):]
    if db_path == ":memory:" or db_path.startswith("file:"):
        return
    parent = Path(db_path).expanduser().resolve().parent
    parent.mkdir(parents=True, exist_ok=True)


def create_engine_and_session(
    database_url: str,
) -> tuple[Any, async_sessionmaker[AsyncSession]]:
    _ensure_sqlite_directory(database_url)
    eng = create_async_engine(database_url, echo=False)
    sess = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    return eng, sess


async def init_db(engine) -> None:
    from things_sdk.db.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
