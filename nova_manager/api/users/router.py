from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from nova_manager.api.users.request_response import (
    IdentifyUserRequest,
    IdentifyUserResponse,
    UpdateUserProfile,
    UserCreate,
    UserResponse,
)
from nova_manager.components.auth.dependencies import require_sdk_app_context
from nova_manager.components.metrics.events_controller import EventsController
from nova_manager.components.users.crud_async import UsersAsyncCRUD
from nova_manager.core.security import SDKAuthContext
from nova_manager.database.async_session import get_async_db
from nova_manager.queues.controller import QueueController

router = APIRouter()


@router.post("/create-user/", response_model=UserResponse)
async def create_user(
    user_data: UserCreate,
    auth: SDKAuthContext = Depends(require_sdk_app_context),
    db: AsyncSession = Depends(get_async_db),
):
    """Create a new user using API key to infer organisation/app"""

    users_crud = UsersAsyncCRUD(db)

    user_id = user_data.user_id
    organisation_id = auth.organisation_id
    app_id = auth.app_id
    user_profile = user_data.user_profile or {}

    existing_user = await users_crud.get_by_user_id(
        user_id=user_id, organisation_id=organisation_id, app_id=app_id
    )

    old_profile = {}

    if existing_user:
        old_profile = existing_user.user_profile.copy()

        # User exists, update user profile with new user_profile
        user = await users_crud.update_user_profile(existing_user, user_profile)
    else:
        # User doesn't exist, create new user with user profile
        user = await users_crud.create_user(
            user_id, organisation_id, app_id, user_profile
        )

    nova_user_id = user.pid

    QueueController().add_task(
        EventsController(organisation_id, app_id).track_user_profile,
        user_id,
        old_profile,
        user_profile,
    )

    return {"nova_user_id": nova_user_id}


@router.post("/update-user-profile/", response_model=UserResponse)
async def update_user_profile(
    user_profile_update: UpdateUserProfile,
    auth: SDKAuthContext = Depends(require_sdk_app_context),
    db: AsyncSession = Depends(get_async_db),
):
    """Update user profile using API key to infer organisation/app"""

    users_crud = UsersAsyncCRUD(db)

    user_id = user_profile_update.user_id
    organisation_id = auth.organisation_id
    app_id = auth.app_id
    user_profile = user_profile_update.user_profile or {}

    existing_user = await users_crud.get_by_user_id(
        user_id=user_id, organisation_id=organisation_id, app_id=app_id
    )

    old_profile = {}

    if existing_user:
        old_profile = existing_user.user_profile.copy()
        user = await users_crud.update_user_profile(existing_user, user_profile)
    else:
        user = await users_crud.create_user(
            user_id, organisation_id, app_id, user_profile
        )

    nova_user_id = user.pid

    QueueController().add_task(
        EventsController(organisation_id, app_id).track_user_profile,
        user_id,
        old_profile,
        user_profile,
    )

    return {"nova_user_id": nova_user_id}


@router.post("/identify/", response_model=IdentifyUserResponse)
async def identify_user(
    data: IdentifyUserRequest,
    auth: SDKAuthContext = Depends(require_sdk_app_context),
    db: AsyncSession = Depends(get_async_db),
):
    """Reconcile an anonymous user to an identified user"""

    if data.anonymous_id == data.identified_id:
        raise HTTPException(status_code=400, detail="anonymous_id and identified_id must be different")

    organisation_id = auth.organisation_id
    app_id = auth.app_id
    users_crud = UsersAsyncCRUD(db)

    anon_user = await users_crud.get_by_user_id(
        user_id=data.anonymous_id, organisation_id=organisation_id, app_id=app_id
    )
    identified_user = await users_crud.get_by_user_id(
        user_id=data.identified_id, organisation_id=organisation_id, app_id=app_id
    )

    merged = False

    if not identified_user:
        identified_user = await users_crud.create_user(
            user_id=data.identified_id,
            organisation_id=organisation_id,
            app_id=app_id,
            user_profile=data.user_profile or {},
        )

    if anon_user:
        anon_profile = anon_user.user_profile or {}
        await users_crud.merge_user_profiles(identified_user, anon_profile, data.user_profile)
        await users_crud.reassign_user_experiences(anon_user.pid, identified_user.pid)
        await users_crud.delete_user(anon_user)
        await db.commit()
        await db.refresh(identified_user)
        merged = True

    events_controller = EventsController(organisation_id, app_id)

    QueueController().add_task(
        events_controller.reconcile_user_in_clickhouse,
        data.anonymous_id,
        data.identified_id,
    )

    if merged:
        QueueController().add_task(
            events_controller.track_user_profile,
            data.identified_id,
            {},
            identified_user.user_profile or {},
        )

    return {"nova_user_id": identified_user.pid, "merged": merged}
