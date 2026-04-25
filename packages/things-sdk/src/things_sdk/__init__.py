"""Things SDK — reusable core library for Things Cloud sync.

Usage::

    from things_sdk import ThingsClient, TaskService, create_engine_and_session, init_db, configure_sync

    # 1. Set up database
    engine, session_factory = create_engine_and_session("sqlite+aiosqlite:///data/things.db")
    await init_db(engine)

    # 2. Configure sync engine
    configure_sync(my_config)  # any object with SyncConfig protocol attrs

    # 3. Use cloud client
    client = ThingsClient(email="...", password="...")
    async with session_factory() as session:
        result = await pull_sync(client, session)

    # 4. Use task service
    svc = TaskService()
    async with session_factory() as session:
        tasks = await svc.list_tasks(session)
"""

from things_sdk.cloud.client import ThingsCloudClient as ThingsClient, ThingsCloudAuthError
from things_sdk.cloud.sync import (
    SyncCircuitOpenError,
    configure as configure_sync,
    parse_notes,
    pull_sync,
    push_sync,
)
from things_sdk.db.engine import create_engine_and_session, init_db
from things_sdk.db.models import Area, Base, ChecklistItem, SyncState, Tag, Task, TaskTag
from things_sdk.errors import EntityNotFoundError, ThingsSDKError
from things_sdk.protocols import CloudClientProtocol, DefaultSyncConfig, SyncConfig
from things_sdk.tags import AmbiguousTagError, TagService
from things_sdk.tasks import TaskService

__all__ = [
    # Client
    "ThingsClient",
    "ThingsCloudAuthError",
    "CloudClientProtocol",
    "ThingsSDKError",
    "EntityNotFoundError",
    # Sync
    "configure_sync",
    "pull_sync",
    "push_sync",
    "parse_notes",
    "SyncCircuitOpenError",
    "SyncConfig",
    "DefaultSyncConfig",
    # Database
    "create_engine_and_session",
    "init_db",
    "Base",
    # Models
    "Task",
    "Area",
    "Tag",
    "TaskTag",
    "ChecklistItem",
    "SyncState",
    # Services
    "TaskService",
    "TagService",
    "AmbiguousTagError",
]
