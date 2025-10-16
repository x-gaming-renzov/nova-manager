from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from nova_manager.api.personalisations.request_response import (
    PersonalisationDetailedResponse,
    PersonalisationUpdate,
)


class PlaygroundSessionResponse(BaseModel):
    session_id: UUID
    token: str
    sdk_key: str
    user_id: UUID
    personalisation_id: UUID
    expires_at: datetime | None = None
    personalisation: PersonalisationDetailedResponse


class PlaygroundPersonalisationUpdate(PersonalisationUpdate):
    """Type alias for clarity when updating playground personalisations."""


__all__ = [
    "PlaygroundSessionResponse",
    "PlaygroundPersonalisationUpdate",
]
