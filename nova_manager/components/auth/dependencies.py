from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import List, Optional

from nova_manager.core.security import (
    verify_token,
    decode_token_ignore_expiry,
    create_auth_context,
    validate_sdk_api_key,
    validate_playground_session_token,
    create_sdk_auth_context,
    is_playground_token,
    AuthContext,
    SDKAuthContext,
)
from nova_manager.core.enums import UserRole
from nova_manager.core.log import logger

# OAuth2 scheme for extracting Bearer tokens
security = HTTPBearer()


async def get_current_auth(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> AuthContext:
    """Extract and validate auth context from JWT token"""

    token = credentials.credentials
    payload = verify_token(token)

    # Ensure this is an access token (not refresh token)
    if payload.get("type") == "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token cannot be used for API access",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return create_auth_context(payload)


async def require_org_context(
    auth: AuthContext = Depends(get_current_auth),
) -> AuthContext:
    """Require user to have organisation context (for org-level operations)"""

    if not auth.organisation_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organisation context required",
        )
    return auth


async def require_app_context(
    auth: AuthContext = Depends(get_current_auth),
) -> AuthContext:
    """Require user to have app context (for app-level operations)"""

    if not auth.organisation_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organisation context required",
        )

    if not auth.app_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="App context required. Please create an app first.",
        )

    return auth


async def get_current_auth_ignore_expiry(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Optional[AuthContext]:
    """Extract auth context from JWT token ignoring expiration (for refresh operations)"""

    try:
        token = credentials.credentials
        payload = decode_token_ignore_expiry(token)

        # Ensure this is an access token (not refresh token)
        if payload.get("type") == "refresh":
            return None

        return create_auth_context(payload)
    except Exception as e:
        # If token is invalid, return None instead of raising exception
        logger.error(f"Error decoding token: {e}")
        return None


def require_roles(allowed_roles: List[UserRole]):
    """
    Decorator factory for role-based access control
    This combines authentication + app context + role validation

    Usage:
    @router.post("/invite")
    async def send_invitation(
        invite_data: InviteRequest,
        auth: AuthContext = Depends(require_roles(["admin", "owner"]))
    ):
    """

    def dependency(auth: AuthContext = Depends(require_app_context)) -> AuthContext:
        # require_app_context already validates:
        # - JWT token is valid
        # - User belongs to organization
        # - User has active app selected
        # - Returns AuthContext with org_id, app_id, user_id, email, role

        # Now add role validation on top
        if auth.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required roles: {', '.join(allowed_roles)}. Your role: {auth.role}",
            )
        return auth

    return dependency


# Convenience functions for common role combinations
async def require_admin_or_owner(
    auth: AuthContext = Depends(require_roles(UserRole.admin_roles())),
) -> AuthContext:
    """Require admin or owner role"""

    return auth


async def require_owner_only(
    auth: AuthContext = Depends(require_roles([UserRole.OWNER])),
) -> AuthContext:
    """Require owner role only"""

    return auth


async def require_analyst_roles(
    auth: AuthContext = Depends(require_roles(UserRole.analyst_roles())),
) -> AuthContext:
    """Require analyst roles only"""

    return auth


async def require_developer_roles(
    auth: AuthContext = Depends(require_roles(UserRole.developer_roles())),
) -> AuthContext:
    """Require developer roles only"""

    return auth


async def get_sdk_auth(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> SDKAuthContext:
    """Extract and validate auth context from JWT token"""

    token = credentials.credentials
    if is_playground_token(token):
        payload = validate_playground_session_token(token)
    else:
        payload = validate_sdk_api_key(token)

    return create_sdk_auth_context(payload)


async def require_sdk_app_context(
    auth: SDKAuthContext = Depends(get_sdk_auth),
) -> SDKAuthContext:
    """Require SDK app context"""

    if not auth.organisation_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organisation context required",
        )

    if not auth.app_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="App context required",
        )

    return auth


async def require_playground_session(
    auth: SDKAuthContext = Depends(get_sdk_auth),
) -> SDKAuthContext:
    """Require a valid playground session token."""

    if not auth.is_playground:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Playground session token required",
        )

    return auth
