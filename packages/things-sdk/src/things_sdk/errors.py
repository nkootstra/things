"""SDK domain exceptions."""

from __future__ import annotations


class ThingsSDKError(Exception):
    """Base SDK exception."""


class EntityNotFoundError(ThingsSDKError):
    """Raised when a requested entity does not exist."""

    def __init__(self, entity_name: str, identifier: str):
        self.entity_name = entity_name
        self.identifier = identifier
        super().__init__(f"{entity_name} not found: {identifier}")
