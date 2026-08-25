import hashlib
import logging

import httpx

from nova_manager.core.config import NOTICE_SERVICE_URL, NOTICE_SERVICE_SECRET

_logger = logging.getLogger(__name__)


async def notify_notice_service(
    org_id: str, app_id: str, experience_names: list[str], event_type: str
):
    """Fire-and-forget POST to the notice service. Never blocks the caller."""
    if not experience_names:
        return
    try:
        signature = hashlib.sha256(f"{org_id}:{app_id}".encode()).hexdigest()
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{NOTICE_SERVICE_URL}/notify",
                json={
                    "type": event_type,
                    "public_signature": signature,
                    "experience_ids": experience_names,
                },
                headers={"X-Internal-Secret": NOTICE_SERVICE_SECRET},
                timeout=5.0,
            )
    except Exception:
        _logger.warning("Failed to notify notice service", exc_info=True)
