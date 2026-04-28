"""API key authentication dependency."""

import os
import secrets

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

import things_api.config as config

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def _valid_keys() -> list[str]:
    """Collect every accepted API key, preferring runtime env over startup config.

    During key rotation the operator may set ``API_KEY_NEXT`` without
    restarting the process; reading env at request time honours that.
    Falls back to the validated startup ``settings`` so config defaults
    and tests that reload config still work.
    """
    keys: list[str] = []
    for env_name, settings_attr in (
        ("API_KEY", "api_key"),
        ("API_KEY_NEXT", "api_key_next"),
    ):
        value = os.environ.get(env_name) or getattr(config.settings, settings_attr, None)
        if value:
            keys.append(value)
    return keys


async def require_api_key(api_key: str | None = Security(API_KEY_HEADER)) -> str:
    valid_keys = _valid_keys()

    if not valid_keys:
        # Fail closed: a deployment with no API key configured is misconfigured.
        # Returning "" here previously allowed all requests through.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server not configured: API_KEY is not set",
        )

    if not api_key or not any(secrets.compare_digest(api_key, key) for key in valid_keys):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
    return api_key
