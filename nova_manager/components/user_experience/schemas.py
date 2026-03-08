from typing import Any, Dict
from datetime import datetime
from typing_extensions import TypedDict
from uuid import UUID
from pydantic import BaseModel


class ExperienceFeatureAssignment(TypedDict):
    feature_id: str
    feature_name: str
    variant_id: str | None
    variant_name: str | None
    config: Dict[str, Any]


class UserExperienceAssignment(BaseModel):
    """The resolved experience assignment for a user.

    Attributes:
        experience_id: Internal UUID of the experience.
        personalisation_id: UUID of the matched personalisation, or ``None``
            if no personalisation matched (default features returned).
        personalisation_name: Human-readable name of the matched personalisation.
        experience_variant_id: UUID of the selected experience variant.
        features: Mapping of feature name → assigned variant details.
        evaluation_reason: Why this assignment was made. Common values:

            - ``personalisation_match`` — a personalisation rule matched
              (may have used runtime ``payload`` context).
            - ``personalisation_reassignment`` — re-evaluated due to
              ``reassign=True`` on the personalisation.
            - ``default_experience`` — no personalisations configured.
            - ``assigned_from_cache: <reason>`` — returned from cache.
            - ``no_experience_assignment_error`` — fallback (should not happen).
        assigned_at: Timestamp of the cached assignment, if loaded from cache.
    """

    experience_id: UUID
    personalisation_id: UUID | None
    personalisation_name: str | None
    experience_variant_id: UUID | None
    features: Dict[str, ExperienceFeatureAssignment]
    evaluation_reason: str
    assigned_at: datetime | None = None

    class Config:
        from_attributes = True
