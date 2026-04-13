"""Single-password authentication for LOLM Training Command Center."""

import os
from fastapi import Header, HTTPException, status


DASHBOARD_PASSWORD = os.environ.get("LOLM_DASH_PASSWORD", "lolm2026")


async def require_auth(x_api_key: str = Header(default="")):
    """FastAPI dependency — checks X-API-Key header against env password."""
    if not x_api_key or x_api_key != DASHBOARD_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key",
        )
