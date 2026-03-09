import traceback
from typing import Dict
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
    Get the assigned variant for a single experience for a user.

    The ``payload`` dict provides runtime context that is merged with the
    user's stored ``user_profile`` when evaluating personalisation rules.
    ``user_profile`` values take precedence over ``payload`` for overlapping
    keys. The stored profile is never modified by ``payload``.

    Personalisations that target transient payload fields should have
    ``reassign=True`` so cached assignments are re-evaluated each request.
    """
    try:
        flow = GetUserExperienceVariantFlowAsync(db)

        result = await flow.get_user_experience_variant(
            user_id=request.user_id,
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
    Get assigned variants for multiple experiences for a user.

    The ``payload`` dict provides runtime context that is merged with the
    user's stored ``user_profile`` when evaluating personalisation rules.
    ``user_profile`` values take precedence over ``payload`` for overlapping
    keys. The stored profile is never modified by ``payload``.

    When ``experience_names`` is provided, only those experiences are evaluated.
    """
    try:
        flow = GetUserExperienceVariantFlowAsync(db)

        results = await flow.get_user_experience_variants(
            user_id=request.user_id,
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
    Get assigned variants for all active experiences for a user.

    The ``payload`` dict provides runtime context that is merged with the
    user's stored ``user_profile`` when evaluating personalisation rules.
    ``user_profile`` values take precedence over ``payload`` for overlapping
    keys. The stored profile is never modified by ``payload``.
    """
    try:
        flow = GetUserExperienceVariantFlowAsync(db)

        # Call without feature_names to get all variants
        results = await flow.get_user_experience_variants(
            user_id=request.user_id,
            organisation_id=auth.organisation_id,
            app_id=auth.app_id,
            payload=request.payload,
            experience_names=None,  # None means get all
        )

        return results

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
