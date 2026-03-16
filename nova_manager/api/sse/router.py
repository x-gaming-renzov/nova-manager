"""
SSE Router — /api/v1/sse/
─────────────────────────────────────────────────────────────────────────────
Server-Sent Events endpoint for real-time experience updates.

Clients subscribe with a set of experience_names. When a personalisation
on any of those experiences is created/updated/enabled/disabled, the server
pushes a lightweight "pull_update" event telling the client to re-evaluate.

Authentication: SDK API key via Bearer header OR ``token`` query param
(for clients like EventSource that don't support custom headers).
Every event includes organisation_id and app_id.
"""

import asyncio
import json
import uuid
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from nova_manager.core.security import (
    validate_sdk_api_key,
    create_sdk_auth_context,
    SDKAuthContext,
)
from nova_manager.api.sse.hub import sse_hub

logger = logging.getLogger(__name__)

router = APIRouter()

HEARTBEAT_INTERVAL = 30  # seconds


def _extract_sdk_auth(request: Request, token: Optional[str]) -> SDKAuthContext:
    """
    Extract SDK auth from either:
    1. ``token`` query param (for EventSource clients)
    2. ``Authorization: Bearer <key>`` header (standard)
    """

    # Prefer query param (EventSource can't set headers)
    api_key = token

    # Fall back to Authorization header
    if not api_key:
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            api_key = auth_header[7:]

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="SDK API key required (token query param or Authorization header)",
        )

    payload = validate_sdk_api_key(api_key)
    return create_sdk_auth_context(payload)


async def _event_stream(
    sub_id: str,
    request: Request,
):
    """Async generator yielding SSE events."""

    sub = sse_hub._subscribers.get(sub_id)
    if not sub:
        return

    try:
        # Send initial connection event
        init_event = {
            "type": "connected",
            "organisation_id": sub.organisation_id,
            "app_id": sub.app_id,
            "experience_names": list(sub.experience_names),
        }
        yield f"event: connected\ndata: {json.dumps(init_event)}\n\n"

        while True:
            # Check if client disconnected
            if await request.is_disconnected():
                break

            try:
                # Wait for event with timeout (for heartbeat)
                event = await asyncio.wait_for(
                    sub.queue.get(), timeout=HEARTBEAT_INTERVAL
                )
                yield f"event: pull_update\ndata: {json.dumps(event)}\n\n"

            except asyncio.TimeoutError:
                # Send heartbeat to keep connection alive
                yield f"event: heartbeat\ndata: {{}}\n\n"

    finally:
        sse_hub.unsubscribe(sub_id)


@router.get("/pull_update")
async def sse_pull_update(
    request: Request,
    experience_names: str = Query(
        ...,
        description=(
            "Comma-separated list of experience names to watch. "
            "e.g. tournament_notice_abc,tournament_notice_def"
        ),
    ),
    token: Optional[str] = Query(
        None,
        description="SDK API key (alternative to Authorization header for EventSource clients)",
    ),
):
    """
    Subscribe to real-time updates for specific experiences.

    Opens a persistent SSE connection. The server pushes a ``pull_update``
    event whenever a personalisation on any of the watched experiences is
    created, updated, enabled, or disabled.

    The event payload contains:
    - ``experience_name``: which experience changed
    - ``reason``: what happened (personalisation_created, etc.)
    - ``organisation_id``: org scope
    - ``app_id``: app scope

    The client should re-call ``POST /get-experiences/`` to fetch fresh data.

    Authentication: SDK API key via Bearer header or ``token`` query param.
    """

    auth = _extract_sdk_auth(request, token)

    names = {n.strip() for n in experience_names.split(",") if n.strip()}

    if not names:
        return {"error": "experience_names is required"}

    sub_id = str(uuid.uuid4())

    sse_hub.subscribe(
        sub_id=sub_id,
        organisation_id=auth.organisation_id,
        app_id=auth.app_id,
        experience_names=names,
    )

    return StreamingResponse(
        _event_stream(sub_id, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )
