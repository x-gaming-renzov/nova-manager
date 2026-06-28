"""Shared-secret access control for privileged surfaces.

A single ``NOVA_ADMIN_KEY`` (see ``core.config``) gates three things HQ flagged
as over-exposed:

* the interactive API docs (``/docs``, ``/redoc``, ``/openapi.json``) — via HTTP
  Basic so a browser prompts for it;
* self-service ``POST /api/v1/auth/register`` — via the ``X-Nova-Admin-Key`` header;
* the destructive admin cleanup endpoint — same header.

Both checks **fail closed**: if ``NOVA_ADMIN_KEY`` is not configured, access is
denied rather than silently allowed, so a missing env var can never leave these
surfaces open.
"""

import hmac

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader, HTTPBasic, HTTPBasicCredentials

from nova_manager.core.config import NOVA_ADMIN_KEY

ADMIN_KEY_HEADER = "X-Nova-Admin-Key"

# auto_error=False so a missing header yields 401 from us (with a clear message)
# instead of FastAPI's generic 403.
_api_key_header = APIKeyHeader(name=ADMIN_KEY_HEADER, auto_error=False)
_basic = HTTPBasic(auto_error=False)


def _matches(candidate: str | None) -> bool:
    """Constant-time compare against the configured key. False when either side
    is missing, so an unset key denies everything."""
    if not NOVA_ADMIN_KEY or not candidate:
        return False
    return hmac.compare_digest(candidate, NOVA_ADMIN_KEY)


async def require_admin_key(api_key: str | None = Depends(_api_key_header)) -> None:
    """Require the shared admin key in the ``X-Nova-Admin-Key`` header."""
    if not _matches(api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Missing or invalid {ADMIN_KEY_HEADER}",
        )


async def require_docs_access(
    credentials: HTTPBasicCredentials | None = Depends(_basic),
) -> None:
    """Gate the docs behind HTTP Basic: any username, password is the admin key.
    Returns a ``WWW-Authenticate`` challenge so browsers show a login prompt."""
    password = credentials.password if credentials else None
    if not _matches(password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
