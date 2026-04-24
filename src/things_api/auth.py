"""API key authentication dependency."""

import os
import secrets

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(api_key: str | None = Security(API_KEY_HEADER)) -> str:
    expected = os.environ.get("API_KEY", "")
    expected_next = os.environ.get("API_KEY_NEXT", "")

    valid_keys = [k for k in (expected, expected_next) if k]
    if not valid_keys:
        return ""

    if not api_key or not any(secrets.compare_digest(api_key, key) for key in valid_keys):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
    return api_key
