from uuid import UUID as UUIDType
from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    user_id: str
    user_profile: dict | None


class UserResponse(BaseModel):
    nova_user_id: UUIDType


class UpdateUserProfile(BaseModel):
    user_id: str
    user_profile: dict | None


class IdentifyUserRequest(BaseModel):
    """Request to reconcile an anonymous user to an identified user.

    When a user transitions from anonymous to identified (e.g. after login
    or signup), this endpoint merges the anonymous user's profile and
    experience assignments into the identified user, then deletes the
    anonymous user record.

    Attributes:
        anonymous_id: External ID of the anonymous user to reconcile from.
        identified_id: External ID of the identified user to reconcile to.
            If this user does not exist yet, it will be created.
        user_profile: Optional profile dict to merge on top. Merge precedence
            (lowest → highest): anonymous profile → identified profile →
            this ``user_profile`` field. Omit to merge only the existing
            anonymous and identified profiles.

    Profile merge precedence::

        base = {**anon_user.user_profile, **identified_user.user_profile, **request.user_profile}

    Example::

        {
            "anonymous_id": "anon_abc123",
            "identified_id": "user_42",
            "user_profile": {"preferred_language": "en"}
        }
    """

    anonymous_id: str = Field(description="External ID of the anonymous user to reconcile from.")
    identified_id: str = Field(description="External ID of the identified user to reconcile to.")
    user_profile: dict | None = Field(
        default=None,
        description=(
            "Optional profile to merge on top of the anonymous and identified "
            "profiles. Highest precedence in the merge."
        ),
    )


class IdentifyUserResponse(BaseModel):
    """Response from the identify (anonymous → identified reconciliation) endpoint.

    Attributes:
        nova_user_id: Internal UUID of the identified user (the surviving record).
        merged: ``True`` if an anonymous user was found in Postgres and its
            profile + experience assignments were merged into the identified user.
            ``False`` if the anonymous user was not found in Postgres (ClickHouse
            reconciliation is still enqueued regardless).
    """

    nova_user_id: UUIDType = Field(description="Internal UUID of the identified user.")
    merged: bool = Field(
        description=(
            "True if an anonymous user existed and was merged into the "
            "identified user. False if only ClickHouse reconciliation was enqueued."
        ),
    )
