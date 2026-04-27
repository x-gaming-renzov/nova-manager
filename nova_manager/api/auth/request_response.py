from typing import Optional
from pydantic import BaseModel, EmailStr, Field, field_validator
from uuid import UUID


class AuthUserRegister(BaseModel):
    """Registration request schema"""

    email: EmailStr
    password: str = Field(
        ..., min_length=6, description="Password must be at least 6 characters"
    )
    name: str = Field(
        ..., min_length=2, description="Name must be at least 2 characters"
    )
    invite_token: Optional[str] = None  # Optional invitation token
    company: Optional[str] = Field(
        None,
        description="Company name (required for self-signup, null for invited users)",
    )

    @field_validator("company")
    @classmethod
    def validate_company(cls, v, info):
        """Validate company field based on whether it's an invite signup"""
        # If there's an invite_token, company should be null
        if info.data.get("invite_token"):
            return None  # Force null for invited users
        # If no invite_token, company is required and must be at least 2 characters
        if not v or len(v.strip()) < 2:
            raise ValueError(
                "Company name is required for self-signup and must be at least 2 characters"
            )
        return v.strip()


class AuthUserLogin(BaseModel):
    """Login request schema"""

    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Token response schema"""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until access token expires


class RefreshTokenRequest(BaseModel):
    """Refresh token request schema"""

    refresh_token: str


class AuthUserResponse(BaseModel):
    """Auth user response schema (no internal IDs exposed)"""

    name: str
    email: str
    has_apps: bool  # Whether user has created any apps
    role: str  # User role in the organization


class AppCreate(BaseModel):
    """App creation request schema"""

    name: str = Field(
        ..., min_length=2, description="App name must be at least 2 characters"
    )
    description: Optional[str] = None


class AppResponse(BaseModel):
    """App response schema (no internal IDs exposed)"""

    id: UUID  # App's public UUID, not internal org/app IDs
    name: str
    description: Optional[str]
    created_at: str


class AppCreateResponse(BaseModel):
    """App creation response with new tokens"""

    app: AppResponse
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until access token expires


class SwitchAppRequest(BaseModel):
    """App switch request schema"""

    app_id: str = Field(..., description="App ID to switch to")


class OrgUserResponse(BaseModel):
    """Organization user response schema"""

    id: UUID
    name: str
    email: str
    role: str  # User role in the organization


class SDKCredentialsResponse(BaseModel):
    """Response schema for SDK credentials"""

    sdk_api_key: str
    backend_url: str
