"""Things API — FastAPI service for Things Cloud sync."""

from things_api.config import settings
from things_sdk import configure_sync

configure_sync(settings)
