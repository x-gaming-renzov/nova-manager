from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from nova_manager.components.invitations.crud import InvitationsCRUD
from nova_manager.components.metrics.events_controller import EventsController
from nova_manager.database.session import get_db
from nova_manager.components.auth.crud import AuthCRUD
from nova_manager.core.enums import UserRole
from nova_manager.api.auth.request_response import (
    AuthUserRegister,
    AuthUserLogin,
    TokenResponse,
    RefreshTokenRequest,
    AuthUserResponse,
    AppCreate,
    AppResponse,
    AppCreateResponse,
    SwitchAppRequest,
    OrgUserResponse,
    SDKCredentialsResponse,
)
from nova_manager.components.auth.dependencies import (
    get_current_auth,
    require_app_context,
    require_org_context,
    get_current_auth_ignore_expiry,
)
from nova_manager.core.security import (
    create_access_token,
    create_refresh_token,
    verify_token,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    AuthContext,
    create_sdk_api_key,
)
from nova_manager.core.config import SDK_BACKEND_URL
from nova_manager.core.log import logger

router = APIRouter()


@router.post("/register", response_model=TokenResponse)
async def register(user_data: AuthUserRegister, db: Session = Depends(get_db)):
    """Register a new user"""
    auth_crud = AuthCRUD(db)

    # Check if user already exists
    existing_user = auth_crud.get_auth_user_by_email(user_data.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists",
        )

    organisation_id = None
    role = UserRole.OWNER  # Default for self-registration

    # Handle invitation-based registration
    if user_data.invite_token:
        invitations_crud = InvitationsCRUD(db)

        # Validate invitation
        invitation = invitations_crud.get_valid_invitation(user_data.invite_token)
        if not invitation:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired invitation token",
            )

        # Verify email matches invitation
        if invitation.email.lower() != user_data.email.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email does not match invitation",
            )

        # Use organization from invitation
        organisation_id = invitation.organisation_id
        role = invitation.role

        # Mark invitation as accepted
        invitations_crud.mark_as_accepted(user_data.invite_token)

    else:
        # Self-registration - create new organisation
        if not user_data.company:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Company name is required for self-registration",
            )
        organisation = auth_crud.create_organisation(name=user_data.company)
        organisation_id = organisation.pid

    # Create auth user
    auth_user = auth_crud.create_auth_user(
        email=user_data.email,
        password=user_data.password,
        name=user_data.name,
        organisation_id=organisation_id,
        role=role,
    )

    # Create tokens (no app_id yet)
    token_data = {
        "auth_user_id": str(auth_user.pid),
        "organisation_id": str(organisation_id),
        "app_id": None,
        "email": auth_user.email,
        "role": auth_user.role,
    }

    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token({"auth_user_id": str(auth_user.pid)})

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/login", response_model=TokenResponse)
async def login(user_data: AuthUserLogin, db: Session = Depends(get_db)):
    """Login user"""
    auth_crud = AuthCRUD(db)

    # Find user
    auth_user = auth_crud.get_auth_user_by_email(user_data.email)
    if not auth_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid credentials"
        )

    # Check password
    if not auth_crud.verify_user_password(auth_user, user_data.password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid credentials"
        )

    # Get user's apps to determine if they have app context
    apps = auth_crud.get_apps_by_organisation(auth_user.organisation_id)
    current_app_id = str(apps[0].pid) if apps else None

    # Create tokens
    token_data = {
        "auth_user_id": str(auth_user.pid),
        "organisation_id": str(auth_user.organisation_id),
        "app_id": current_app_id,
        "email": auth_user.email,
        "role": auth_user.role,
    }

    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token({"auth_user_id": str(auth_user.pid)})

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    refresh_data: RefreshTokenRequest,
    current_auth: Optional[AuthContext] = Depends(get_current_auth_ignore_expiry),
    db: Session = Depends(get_db),
):
    """Refresh access token using refresh token"""
    # Verify refresh token
    payload = verify_token(refresh_data.refresh_token)

    # Ensure this is a refresh token
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid refresh token"
        )

    auth_user_id = payload.get("auth_user_id")
    if not auth_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid refresh token"
        )

    # Get current user data
    auth_crud = AuthCRUD(db)
    auth_user = auth_crud.get_auth_user_by_id(auth_user_id)
    if not auth_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="User not found"
        )

    # Try to preserve current app context using dependency
    current_app_id = current_auth.app_id if current_auth else None

    # If no current app context, get user's apps
    if not current_app_id:
        apps = auth_crud.get_apps_by_organisation(auth_user.organisation_id)
        current_app_id = str(apps[0].pid) if apps else None

    # Create new access token with preserved app context
    token_data = {
        "auth_user_id": str(auth_user.pid),
        "organisation_id": str(auth_user.organisation_id),
        "app_id": current_app_id,
        "email": auth_user.email,
        "role": auth_user.role,
    }

    access_token = create_access_token(token_data)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_data.refresh_token,  # Keep same refresh token
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.get("/me", response_model=AuthUserResponse)
async def get_current_user(
    auth: AuthContext = Depends(get_current_auth), db: Session = Depends(get_db)
):
    """Get current user info"""
    auth_crud = AuthCRUD(db)
    auth_user = auth_crud.get_auth_user_by_id(auth.auth_user_id)

    if not auth_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    has_apps = auth_crud.user_has_apps(auth_user)

    return AuthUserResponse(
        name=auth_user.name,
        email=auth_user.email,
        has_apps=has_apps,
        role=auth_user.role,
    )


@router.get("/sdk-credentials", response_model=SDKCredentialsResponse)
async def get_sdk_credentials(auth: AuthContext = Depends(require_app_context)):
    """Get SDK credentials for the current app"""

    # Generate ultra-compact SDK API key for this org/app combination
    sdk_api_key = create_sdk_api_key(auth.organisation_id, auth.app_id)

    # Get backend URL from config
    backend_url = SDK_BACKEND_URL

    return SDKCredentialsResponse(sdk_api_key=sdk_api_key, backend_url=backend_url)


@router.post("/apps", response_model=AppCreateResponse)
async def create_app(
    app_data: AppCreate,
    auth: AuthContext = Depends(require_org_context),
    db: Session = Depends(get_db),
):
    """Create a new app and return new tokens with app context"""
    auth_crud = AuthCRUD(db)

    # Create app
    app = auth_crud.create_app(
        name=app_data.name,
        organisation_id=auth.organisation_id,
        description=app_data.description,
    )

    try:
        events_controller = EventsController(str(auth.organisation_id), str(app.pid))

        # Create dataset
        events_controller.create_dataset()

        # Create raw events table
        events_controller.create_raw_events_table()

        # Create user profile table
        events_controller.create_user_profile_table()

        # Create user experience table
        events_controller.create_user_experience_table()
    except Exception as e:
        logger.error(f"Failed to provision core BigQuery tables for app {app.pid}: {e}")
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to provision BigQuery tables",
        )

    # Create new tokens with the new app context
    token_data = {
        "auth_user_id": str(auth.auth_user_id),
        "organisation_id": str(auth.organisation_id),
        "app_id": str(app.pid),
        "email": auth.email,
        "role": auth.role,
    }

    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token({"auth_user_id": str(auth.auth_user_id)})

    return AppCreateResponse(
        app=AppResponse(
            id=app.pid,
            name=app.name,
            description=app_data.description,
            created_at=app.created_at.isoformat() if hasattr(app, "created_at") else "",
        ),
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.get("/apps", response_model=list[AppResponse])
async def list_apps(
    auth: AuthContext = Depends(require_org_context), db: Session = Depends(get_db)
):
    """List user's apps"""
    auth_crud = AuthCRUD(db)

    apps = auth_crud.get_apps_by_organisation(auth.organisation_id)

    return [
        AppResponse(
            id=app.pid,
            name=app.name,
            description=getattr(app, "description", None),
            created_at=app.created_at.isoformat() if hasattr(app, "created_at") else "",
        )
        for app in apps
    ]


@router.post("/switch-app", response_model=TokenResponse)
async def switch_app(
    switch_data: SwitchAppRequest,
    auth: AuthContext = Depends(require_org_context),
    db: Session = Depends(get_db),
):
    """Switch to a different app context"""
    auth_crud = AuthCRUD(db)

    # Verify the app belongs to the user's organisation
    app = auth_crud.get_app_by_id(switch_data.app_id, auth.organisation_id)
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="App not found"
        )

    # Create new access token with the new app context
    token_data = {
        "auth_user_id": str(auth.auth_user_id),
        "organisation_id": str(auth.organisation_id),
        "app_id": switch_data.app_id,
        "email": auth.email,
        "role": auth.role,
    }

    access_token = create_access_token(token_data)

    # Generate new refresh token as well
    refresh_token = create_refresh_token({"auth_user_id": str(auth.auth_user_id)})

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.get("/users", response_model=list[OrgUserResponse])
async def list_org_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    auth: AuthContext = Depends(require_org_context),
    db: Session = Depends(get_db),
):
    """List all users in the current organisation"""
    auth_crud = AuthCRUD(db)
    users = auth_crud.get_users_by_organisation(
        auth.organisation_id, skip=skip, limit=limit
    )

    return [
        OrgUserResponse(id=u.pid, name=u.name, email=u.email, role=u.role)
        for u in users
    ]
