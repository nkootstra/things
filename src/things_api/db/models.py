"""Re-export domain models from SDK for backward compatibility."""

from things_sdk.db.models import (  # noqa: F401
    Area,
    Base,
    ChecklistItem,
    SyncState,
    Tag,
    Task,
)
