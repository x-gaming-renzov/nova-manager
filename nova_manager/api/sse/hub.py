"""
SSE Connection Hub
─────────────────────────────────────────────────────────────────────────────
In-process pub/sub for Server-Sent Events.

Subscribers register with (org_id, app_id, experience_names).
When a personalisation changes, the hub notifies matching subscribers.

This is intentionally simple — single-process, no Redis pub/sub.
For multi-process deployments, swap the in-memory dict for Redis channels.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, Set, Optional

logger = logging.getLogger(__name__)


@dataclass
class SSESubscription:
    """A single SSE client subscription."""

    organisation_id: str
    app_id: str
    experience_names: Set[str]
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)


class SSEHub:
    """Global hub managing all active SSE subscriptions."""

    def __init__(self):
        self._subscribers: Dict[str, SSESubscription] = {}  # sub_id → subscription

    def subscribe(
        self,
        sub_id: str,
        organisation_id: str,
        app_id: str,
        experience_names: Set[str],
    ) -> SSESubscription:
        """Register a new SSE subscriber."""
        sub = SSESubscription(
            organisation_id=organisation_id,
            app_id=app_id,
            experience_names=experience_names,
        )
        self._subscribers[sub_id] = sub
        logger.info(
            f"[SSE] subscribe: {sub_id} org={organisation_id} "
            f"experiences={experience_names}"
        )
        return sub

    def unsubscribe(self, sub_id: str):
        """Remove a subscriber."""
        removed = self._subscribers.pop(sub_id, None)
        if removed:
            logger.info(f"[SSE] unsubscribe: {sub_id}")

    def notify(
        self,
        organisation_id: str,
        app_id: str,
        experience_name: str,
        reason: str,
    ):
        """
        Notify all subscribers watching this experience.
        Called from personalisation CRUD endpoints (create/update/enable/disable).
        """
        for sub_id, sub in self._subscribers.items():
            if (
                sub.organisation_id == organisation_id
                and sub.app_id == app_id
                and experience_name in sub.experience_names
            ):
                event = {
                    "experience_name": experience_name,
                    "reason": reason,
                    "organisation_id": organisation_id,
                    "app_id": app_id,
                }
                try:
                    sub.queue.put_nowait(event)
                    logger.info(
                        f"[SSE] notify: {sub_id} ← {experience_name} ({reason})"
                    )
                except asyncio.QueueFull:
                    logger.warning(f"[SSE] queue full for {sub_id}, dropping event")

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


# Global singleton
sse_hub = SSEHub()
