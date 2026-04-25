"""Re-export task service from SDK + provide FastAPI DI factory."""

from things_sdk.tasks import TaskService  # noqa: F401
from things_api.services.contracts import TaskServiceProtocol


def get_task_service() -> TaskServiceProtocol:
    return TaskService()
