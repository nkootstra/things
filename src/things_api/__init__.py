"""Things API — FastAPI service for Things Cloud sync."""

from things_api.config import settings
from things_sdk.cloud.sync import configure as _configure_sync

_configure_sync(settings)
