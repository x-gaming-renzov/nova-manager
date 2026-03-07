from uuid import UUID as UUIDType
from pydantic import BaseModel


class UserCreate(BaseModel):
    user_id: str
    user_profile: dict | None


class UserResponse(BaseModel):
    nova_user_id: UUIDType


class UpdateUserProfile(BaseModel):
    user_id: str
    user_profile: dict | None


class IdentifyUserRequest(BaseModel):
    anonymous_id: str
    identified_id: str
    user_profile: dict | None = None


class IdentifyUserResponse(BaseModel):
    nova_user_id: UUIDType
    merged: bool
