#!/usr/bin/env python
"""
Nova Notice Service — Standalone SSE relay for real-time personalisation updates.

Runs on a dedicated VM (not Cloud Run) to maintain persistent SSE connections.
Cloud Run POSTs change events here; this service fans them out to SDK clients.

Usage:
    python scripts/run_notice_service.py
"""

import sys
import os
import signal
import asyncio
import hashlib
import hmac
import json
import logging
from collections import defaultdict
from typing import Optional

# Add project root to path (same pattern as run_worker.py)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from nova_manager.core.config import NOTICE_SERVICE_SECRET
from nova_manager.core.security import validate_sdk_api_key
from nova_manager.core.log import configure_logging

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Query, status
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

configure_logging()
logger = logging.getLogger("notice_service")

# ── In-memory subscription store ────────────────────────────────────────────
# key = sha256(org_id:app_id), value = list of (queue, experience_names_set)
subscriptions: dict[str, list[tuple[asyncio.Queue, set[str]]]] = defaultdict(list)

# ── Request models ──────────────────────────────────────────────────────────

class NotifyRequest(BaseModel):
    type: str
    public_signature: str
    experience_ids: list[str]

# ── FastAPI app ─────────────────────────────────────────────────────────────

app = FastAPI(title="Nova Notice Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

HEARTBEAT_INTERVAL = 30  # seconds


def _compute_signature(org_id: str, app_id: str) -> str:
    return hashlib.sha256(f"{org_id}:{app_id}".encode()).hexdigest()


def _extract_api_key(request: Request, token: Optional[str]) -> str:
    """Extract SDK API key from Bearer header or token query param."""
    if token:
        return token

    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="SDK API key required (Authorization header or token query param)",
    )


# ── POST /notify — called by Cloud Run ──────────────────────────────────────

@app.post("/notify")
async def notify(body: NotifyRequest, request: Request):
    # Verify internal secret
    provided = request.headers.get("x-internal-secret", "")
    if not NOTICE_SERVICE_SECRET or not hmac.compare_digest(
        provided.encode(), NOTICE_SERVICE_SECRET.encode()
    ):
        raise HTTPException(status_code=401, detail="Invalid internal secret")

    subs = subscriptions.get(body.public_signature, [])
    notified = 0
    event = {"type": body.type, "experience_ids": body.experience_ids}
    event_ids = set(body.experience_ids)

    for queue, names in subs:
        # Only relay if subscriber watches at least one affected experience
        if names.intersection(event_ids):
            try:
                queue.put_nowait(event)
                notified += 1
            except asyncio.QueueFull:
                logger.warning("Subscriber queue full, dropping event")

    logger.info(
        "Notified %d subscriber(s) for signature %.8s… [%s]",
        notified, body.public_signature, body.type,
    )
    return {"ok": True, "notified": notified}


# ── GET /subscribe — called by SDK clients ──────────────────────────────────

async def _event_stream(queue: asyncio.Queue, request: Request):
    """Async generator yielding SSE events."""
    yield f"event: connected\ndata: {{}}\n\n"

    try:
        while True:
            if await request.is_disconnected():
                break

            try:
                event = await asyncio.wait_for(
                    queue.get(), timeout=HEARTBEAT_INTERVAL
                )
                yield f"event: pull_update\ndata: {json.dumps(event)}\n\n"
            except asyncio.TimeoutError:
                yield "event: heartbeat\ndata: {}\n\n"
    except asyncio.CancelledError:
        pass


@app.get("/subscribe")
async def subscribe(
    request: Request,
    experience_names: str = Query(
        ...,
        description="Comma-separated experience names to watch",
    ),
    token: Optional[str] = Query(None, description="SDK API key (alternative to Authorization header)"),
):
    api_key = _extract_api_key(request, token)
    payload = validate_sdk_api_key(api_key)
    signature = _compute_signature(payload["organisation_id"], payload["app_id"])

    names_set = {n.strip() for n in experience_names.split(",") if n.strip()}
    if not names_set:
        raise HTTPException(status_code=400, detail="experience_names is required")

    queue: asyncio.Queue = asyncio.Queue(maxsize=64)
    entry = (queue, names_set)
    subscriptions[signature].append(entry)

    logger.info(
        "New subscriber for signature %.8s… watching %d experience(s) (total: %d)",
        signature, len(names_set), len(subscriptions[signature]),
    )

    async def stream_with_cleanup():
        try:
            async for event in _event_stream(queue, request):
                yield event
        finally:
            try:
                subscriptions[signature].remove(entry)
                if not subscriptions[signature]:
                    del subscriptions[signature]
            except (ValueError, KeyError):
                pass
            logger.info(
                "Subscriber disconnected from %.8s… (remaining: %d)",
                signature, len(subscriptions.get(signature, [])),
            )

    return StreamingResponse(
        stream_with_cleanup(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── GET /health ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    total = sum(len(v) for v in subscriptions.values())
    return {"status": "healthy", "subscribers": total}


# ── Entrypoint ──────────────────────────────────────────────────────────────

def handle_sigterm(signum, frame):
    logger.info("Received signal %s. Shutting down…", signum)
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    port = int(os.environ.get("PORT", "8001"))
    logger.info("Starting notice service on port %d", port)
    uvicorn.run(app, host="0.0.0.0", port=port)
