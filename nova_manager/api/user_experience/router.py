import traceback
from typing import Dict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from nova_manager.database.async_session import get_async_db
from nova_manager.api.user_experience.request_response import (
    GetExperienceRequest,
    GetExperiencesRequest,
)
from nova_manager.components.user_experience.schemas import UserExperienceAssignment
from nova_manager.flows.get_user_experience_variant_flow_async import (
    GetUserExperienceVariantFlowAsync,
)
from nova_manager.components.auth.dependencies import require_sdk_app_context
from nova_manager.core.security import SDKAuthContext

router = APIRouter()


@router.post("/get-experience/", response_model=UserExperienceAssignment)
async def get_user_experience_variant(
    request: GetExperienceRequest,
    auth: SDKAuthContext = Depends(require_sdk_app_context),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Get variant for a single feature/object for a user.
    """
    try:
        flow = GetUserExperienceVariantFlowAsync(db)

        user_id = _resolve_user_id(request.user_id, auth)

        result = await flow.get_user_experience_variant(
            user_id=user_id,
            experience_name=request.experience_name,
            organisation_id=auth.organisation_id,
            app_id=auth.app_id,
            payload=request.payload,
        )

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/get-experiences/", response_model=Dict[str, UserExperienceAssignment])
async def get_user_experiences(
    request: GetExperiencesRequest,
    auth: SDKAuthContext = Depends(require_sdk_app_context),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Get variants for multiple specific features/objects for a user.
    """
    try:
        flow = GetUserExperienceVariantFlowAsync(db)

        user_id = _resolve_user_id(request.user_id, auth)

        results = await flow.get_user_experience_variants(
            user_id=user_id,
            organisation_id=auth.organisation_id,
            app_id=auth.app_id,
            payload=request.payload,
            experience_names=request.experience_names,
        )

        return results

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/get-all-experiences/", response_model=Dict[str, UserExperienceAssignment]
)
async def get_all_user_experiences(
    request: GetExperiencesRequest,
    auth: SDKAuthContext = Depends(require_sdk_app_context),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Get experiences for all active features/objects for a user.
    """
    try:
        flow = GetUserExperienceVariantFlowAsync(db)

        # Call without feature_names to get all variants
        user_id = _resolve_user_id(request.user_id, auth)

        results = await flow.get_user_experience_variants(
            user_id=user_id,
            organisation_id=auth.organisation_id,
            app_id=auth.app_id,
            payload=request.payload,
            experience_names=None,  # None means get all
        )

        return results

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


def _resolve_user_id(request_user_id: UUID, auth: SDKAuthContext) -> UUID:
    if auth.is_playground:
        if not auth.user_id:
            raise HTTPException(
                status_code=400, detail="Playground token missing user context"
            )
        try:
            return UUID(str(auth.user_id))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    return request_user_id
