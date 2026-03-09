from typing import List, Optional
from pydantic import BaseModel, Field


class GetExperienceRequest(BaseModel):
    """Request to evaluate a single experience for a user.

    Attributes:
        user_id: External user identifier.
        experience_name: Name of the experience to evaluate.
        payload: Optional runtime context dict merged into the evaluation context
            for personalisation rules. Keys in ``payload`` are available to
            personalisation rule conditions alongside the stored ``user_profile``.
            When a key exists in both ``payload`` and ``user_profile``, the
            ``user_profile`` value takes precedence (stored profile is authoritative).
            The user profile is **not** modified by this field.

            Personalisations targeting transient payload fields should have
            ``reassign=True`` so that cached assignments are re-evaluated when
            the payload changes between requests.

    Example::

        {
            "user_id": "player_42",
            "experience_name": "tournament-banner",
            "payload": {"in_tournament": true, "tournament_id": "spring-2026"}
        }
    """

    user_id: str
    experience_name: str
    payload: dict = Field(
        default={},
        description=(
            "Runtime context merged with user_profile for personalisation rule "
            "evaluation. user_profile takes precedence on key conflicts. "
            "Does not modify the stored profile."
        ),
    )


class GetExperiencesRequest(BaseModel):
    """Request to evaluate multiple (or all) experiences for a user.

    Attributes:
        user_id: External user identifier.
        payload: Optional runtime context dict merged into the evaluation context
            for personalisation rules. Keys in ``payload`` are available to
            personalisation rule conditions alongside the stored ``user_profile``.
            When a key exists in both ``payload`` and ``user_profile``, the
            ``user_profile`` value takes precedence (stored profile is authoritative).
            The user profile is **not** modified by this field.

            Personalisations targeting transient payload fields should have
            ``reassign=True`` so that cached assignments are re-evaluated when
            the payload changes between requests.
        experience_names: Optional list of experience names to evaluate.
            When ``None``, all active experiences are returned.

    Example::

        {
            "user_id": "player_42",
            "payload": {"in_tournament": true},
            "experience_names": ["tournament-banner", "checkout-promo"]
        }
    """

    user_id: str
    payload: dict = Field(
        default={},
        description=(
            "Runtime context merged with user_profile for personalisation rule "
            "evaluation. user_profile takes precedence on key conflicts. "
            "Does not modify the stored profile."
        ),
    )
    experience_names: Optional[List[str]] = None
