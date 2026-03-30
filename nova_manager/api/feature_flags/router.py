import traceback
from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session


from nova_manager.api.feature_flags.request_response import (
    FeatureFlagListItem,
    FeatureFlagDetailedResponse,
    NovaObjectSyncRequest,
    NovaObjectSyncResponse,
)
from nova_manager.components.feature_flags.crud import (
    FeatureFlagsCRUD,
)
from nova_manager.components.experiences.crud import (
    ExperiencesCRUD,
    ExperienceFeaturesCRUD,
)
from nova_manager.database.session import get_db
from nova_manager.components.auth.dependencies import (
    require_app_context,
    require_sdk_app_context,
)
from nova_manager.core.security import AuthContext, SDKAuthContext


router = APIRouter()


@router.post("/sync-nova-objects/")
async def sync_nova_objects(
    sync_request: NovaObjectSyncRequest,
    auth: SDKAuthContext = Depends(require_sdk_app_context),
    db: Session = Depends(get_db),
):
    """
    Sync Nova objects from client application to create/update feature flags

    This endpoint:
    1. Takes nova-objects.json structure from client
    2. Creates/updates feature flags for each object
    3. Creates/updates default variants with default values
    4. Returns summary of operations performed
    """

    # Initialize CRUD instances
    flags_crud = FeatureFlagsCRUD(db)
    experiences_crud = ExperiencesCRUD(db)
    experience_features_crud = ExperienceFeaturesCRUD(db)

    # Track statistics
    stats = {
        "objects_processed": 0,
        "objects_created": 0,
        "objects_updated": 0,
        "objects_skipped": 0,
        "experiences_processed": 0,
        "experiences_created": 0,
        "experiences_updated": 0,
        "experiences_skipped": 0,
        "experience_features_created": 0,
        "details": [],
    }

    # Process each object from the sync request
    for object_name, object_props in sync_request.objects.items():
        try:
            stats["objects_processed"] += 1

            # Check if feature flag already exists
            existing_flag = flags_crud.get_by_name(
                name=object_name,
                organisation_id=auth.organisation_id,
                app_id=auth.app_id,
            )

            keys_config = object_props.keys

            # TODO: Add keys_config validation here
            # Update existing flag
            if existing_flag:
                flags_crud.update(
                    db_obj=existing_flag,
                    obj_in={
                        "keys_config": keys_config,
                        "type": object_props.type,
                    },
                )

                stats["objects_updated"] += 1

                stats["details"].append(
                    {
                        "object_name": object_name,
                        "action": "updated",
                        "flag_id": str(existing_flag.pid),
                        "message": "Updated feature flag and default variant",
                    }
                )
            else:
                # Create new feature flag with default variant
                flag_data = {
                    "name": object_name,
                    "description": f"Auto-generated from nova-objects.json for {object_name}",
                    "keys_config": keys_config,
                    "type": object_props.type,
                    "organisation_id": auth.organisation_id,
                    "app_id": auth.app_id,
                    "is_active": True,
                }

                new_flag = flags_crud.create(obj_in=flag_data)

                stats["objects_created"] += 1
                stats["details"].append(
                    {
                        "object_name": object_name,
                        "action": "created",
                        "flag_id": str(new_flag.pid),
                        "message": "Created feature flag with default variant",
                    }
                )

        except Exception as obj_error:
            # Log error but continue with other objects
            stats["objects_skipped"] += 1
            stats["details"].append(
                {
                    "object_name": object_name,
                    "action": "error",
                    "message": f"Failed to process: {str(obj_error)}",
                }
            )
            traceback.print_exc()
            continue

    # Process each experience from the sync request
    for experience_name, experience_props in sync_request.experiences.items():
        try:
            stats["experiences_processed"] += 1

            # Check if experience already exists
            existing_experience = experiences_crud.get_by_name(
                name=experience_name,
                organisation_id=auth.organisation_id,
                app_id=auth.app_id,
            )

            # Update or create experience
            if existing_experience:
                experiences_crud.update(
                    db_obj=existing_experience,
                    obj_in={
                        "description": experience_props.description,
                        "status": "active",  # Default status for synced experiences
                    },
                )
                stats["experiences_updated"] += 1
                experience_action = "updated"
                experience_id = existing_experience.pid
            else:
                # Create new experience
                experience_data = {
                    "name": experience_name,
                    "description": experience_props.description,
                    "status": "active",  # Default status for synced experiences
                    "organisation_id": auth.organisation_id,
                    "app_id": auth.app_id,
                }

                new_experience = experiences_crud.create(obj_in=experience_data)
                stats["experiences_created"] += 1
                experience_action = "created"
                experience_id = new_experience.pid

            # Process experience objects (create ExperienceFeatures)
            experience_features_created = 0
            for object_name in experience_props.objects.keys():
                if not experience_props.objects[object_name]:
                    continue

                # Find the feature flag by name
                feature_flag = flags_crud.get_by_name(
                    name=object_name,
                    organisation_id=auth.organisation_id,
                    app_id=auth.app_id,
                )

                if feature_flag:
                    # Check if ExperienceFeature already exists
                    existing_experience_feature = (
                        experience_features_crud.get_by_experience_and_feature(
                            experience_id=experience_id,
                            feature_id=feature_flag.pid,
                        )
                    )

                    if not existing_experience_feature:
                        # Create ExperienceFeature
                        experience_feature_data = {
                            "experience_id": experience_id,
                            "feature_id": feature_flag.pid,
                        }
                        experience_features_crud.create(obj_in=experience_feature_data)
                        experience_features_created += 1
                        stats["experience_features_created"] += 1

            stats["details"].append(
                {
                    "experience_name": experience_name,
                    "action": experience_action,
                    "experience_id": str(experience_id),
                    "experience_features_created": experience_features_created,
                    "message": f"{experience_action.capitalize()} experience with {experience_features_created} feature connections",
                }
            )

        except Exception as exp_error:
            # Log error but continue with other experiences
            stats["experiences_skipped"] += 1
            stats["details"].append(
                {
                    "experience_name": experience_name,
                    "action": "error",
                    "message": f"Failed to process experience: {str(exp_error)}",
                }
            )
            traceback.print_exc()
            continue

    dashboard_url = "https://dashboard.nova.com/objects"

    return NovaObjectSyncResponse(
        success=True,
        objects_processed=stats["objects_processed"],
        objects_created=stats["objects_created"],
        objects_updated=stats["objects_updated"],
        objects_skipped=stats["objects_skipped"],
        experiences_processed=stats["experiences_processed"],
        experiences_created=stats["experiences_created"],
        experiences_updated=stats["experiences_updated"],
        experiences_skipped=stats["experiences_skipped"],
        experience_features_created=stats["experience_features_created"],
        dashboard_url=dashboard_url,
        message=f"Processed {stats['objects_processed']} objects and {stats['experiences_processed']} experiences successfully",
        details=stats["details"],
    )


@router.get("/", response_model=List[FeatureFlagListItem])
async def list_feature_flags(
    auth: AuthContext = Depends(require_app_context),
    active_only: bool = Query(False),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """List feature flags with pagination"""
    feature_flags_crud = FeatureFlagsCRUD(db)

    if active_only:
        flags = feature_flags_crud.get_active_flags(
            organisation_id=auth.organisation_id, app_id=auth.app_id
        )
    else:
        flags = feature_flags_crud.get_multi(
            skip=skip,
            limit=limit,
            organisation_id=auth.organisation_id,
            app_id=auth.app_id,
        )

    return flags


@router.get("/available/", response_model=List[FeatureFlagListItem])
async def list_available_feature_flags(
    auth: AuthContext = Depends(require_app_context),
    db: Session = Depends(get_db),
):
    """List feature flags that are not assigned to any experience"""
    feature_flags_crud = FeatureFlagsCRUD(db)

    flags = feature_flags_crud.get_available_flags(
        organisation_id=auth.organisation_id, app_id=auth.app_id
    )

    return flags


@router.get("/{flag_pid}/", response_model=FeatureFlagDetailedResponse)
async def get_feature_flag(
    flag_pid: UUID,
    auth: AuthContext = Depends(require_app_context),
    db: Session = Depends(get_db),
):
    """Get feature flag by ID with all variants"""
    feature_flags_crud = FeatureFlagsCRUD(db)

    feature_flag = feature_flags_crud.get_with_full_details(pid=flag_pid)
    if not feature_flag:
        raise HTTPException(status_code=404, detail="Feature flag not found")

    return feature_flag


@router.patch("/{flag_pid}/toggle/", response_model=FeatureFlagListItem)
async def toggle_feature_flag(
    flag_pid: UUID,
    auth: AuthContext = Depends(require_app_context),
    db: Session = Depends(get_db),
):
    """Toggle the is_active status of a feature flag."""
    crud = FeatureFlagsCRUD(db)
    flag = crud.get_by_pid(flag_pid)
    if not flag:
        raise HTTPException(status_code=404, detail="Feature flag not found")
    if str(flag.organisation_id) != str(auth.organisation_id):
        raise HTTPException(status_code=403, detail="Not in your organization")
    if flag.app_id != auth.app_id:
        raise HTTPException(status_code=403, detail="Not in your app")
    return crud.toggle_active(flag_pid)
