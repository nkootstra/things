"""API key authentication dependency."""

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

import os

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(api_key: str | None = Security(API_KEY_HEADER)) -> str:
    expected = os.environ.get("API_KEY", "")
    if not expected:
        return ""
    if not api_key or api_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
    return api_key
