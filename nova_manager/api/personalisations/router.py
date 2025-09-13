from uuid import UUID
from sqlalchemy.orm import Session
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query

from nova_manager.database.session import get_db
from nova_manager.components.auth.dependencies import require_app_context
from nova_manager.core.security import AuthContext
from nova_manager.api.personalisations.request_response import (
    PersonalisationCreate,
    PersonalisationDetailedResponse,
    PersonalisationListResponse,
    PersonalisationUpdate,
)
from nova_manager.components.experiences.crud import (
    ExperiencesCRUD,
    ExperienceVariantsCRUD,
    ExperienceFeatureVariantsCRUD,
)
from nova_manager.components.personalisations.crud import (
    PersonalisationExperienceVariantsCRUD,
    PersonalisationsCRUD,
)
from nova_manager.components.personalisations.schemas import PersonalisationResponse
from nova_manager.components.personalisations.crud import PersonalisationSegmentRulesCRUD
from nova_manager.components.segments.crud import SegmentsCRUD
from nova_manager.components.metrics.crud import (
    MetricsCRUD,
    PersonalisationMetricsCRUD,
)

router = APIRouter()


# Personalisation endpoints
@router.post("/create-personalisation/", response_model=PersonalisationDetailedResponse)
async def create_personalisation(
    personalisation_data: PersonalisationCreate,
    auth: AuthContext = Depends(require_app_context),
    db: Session = Depends(get_db),
):
    """Create a new personalisation for an experience"""
    experiences_crud = ExperiencesCRUD(db)
    personalisations_crud = PersonalisationsCRUD(db)
    experience_variants_crud = ExperienceVariantsCRUD(db)
    experience_feature_variants_crud = ExperienceFeatureVariantsCRUD(db)
    personalisation_experience_variants_crud = PersonalisationExperienceVariantsCRUD(db)
    metrics_crud = MetricsCRUD(db)
    personalisation_metrics_crud = PersonalisationMetricsCRUD(db)

    experience_id = personalisation_data.experience_id
    experience_variants = personalisation_data.experience_variants
    selected_metrics = personalisation_data.selected_metrics

    # Validate experience exists
    experience = experiences_crud.get_with_features(experience_id)
    if not experience:
        raise HTTPException(status_code=404, detail="Experience not found")

    # Validate experience belongs to the same org and app as in token
    if str(experience.organisation_id) != str(auth.organisation_id):
        raise HTTPException(
            status_code=403, detail="Experience does not belong to your organization"
        )

    if experience.app_id != auth.app_id:
        raise HTTPException(
            status_code=403, detail="Experience does not belong to your app"
        )

    # Validate metrics exist and belong to same org/app
    if selected_metrics:
        for metric_id in selected_metrics:
            metric = metrics_crud.get_by_pid(metric_id)
            if not metric:
                raise HTTPException(
                    status_code=404, detail=f"Metric not found: {metric_id}"
                )

            # Validate metric belongs to the same org and app as in token
            if str(metric.organisation_id) != str(auth.organisation_id):
                raise HTTPException(
                    status_code=403,
                    detail=f"Metric {metric_id} does not belong to your organization",
                )

            if metric.app_id != auth.app_id:
                raise HTTPException(
                    status_code=403,
                    detail=f"Metric {metric_id} does not belong to your app",
                )

    # Check if personalisation name already exists in this experience
    existing = personalisations_crud.get_by_name(
        name=personalisation_data.name,
        experience_id=experience_id,
    )
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Personalisation '{personalisation_data.name}' already exists in this experience",
        )

    # Validate that all feature flags exist and belong to this experience and no duplicate experience feature variants and total percentage is 100
    experience_features = [exp_feature.pid for exp_feature in experience.features]

    default_count = 0
    total_percentage = 0

    for i in experience_variants:
        total_percentage += i.target_percentage

        experience_variant = i.experience_variant

        if experience_variant.is_default:
            default_count += 1
            if default_count > 1:
                raise HTTPException(
                    status_code=400,
                    detail="Only one default personalisation can be assigned per segment",
                )

        elif experience_variant.feature_variants:
            seen_experience_feature_ids = set()

            for feature_variant in experience_variant.feature_variants:
                experience_feature_id = feature_variant.experience_feature_id

                if experience_feature_id not in experience_features:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Experience Feature not found: {experience_feature_id}",
                    )

                if experience_feature_id in seen_experience_feature_ids:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Experience Feature {experience_feature_id} is assigned multiple times",
                    )

                seen_experience_feature_ids.add(feature_variant.experience_feature_id)

        else:
            raise HTTPException(
                status_code=400,
                detail="Each Experience Variant must either have feature_variants or is_default=True",
            )

    if total_percentage != 100:
        raise HTTPException(
            status_code=400,
            detail=f"Experience Variant percentages must sum to 100%, got {total_percentage}%",
        )

    max_priority_personalisation = (
        personalisations_crud.get_experience_max_priority_personalisation(
            experience_id=experience_id
        )
    )

    if max_priority_personalisation:
        next_priority = max_priority_personalisation.priority + 1
    else:
        next_priority = 1

    # Create personalisation with variants
    personalisation = personalisations_crud.create_personalisation(
        experience_id=experience_id,
        organisation_id=experience.organisation_id,
        app_id=experience.app_id,
        name=personalisation_data.name,
        description=personalisation_data.description,
        priority=next_priority,
        rule_config=personalisation_data.rule_config,
        rollout_percentage=personalisation_data.rollout_percentage,
    )

    for i in experience_variants:
        target_percentage = i.target_percentage
        experience_variant = i.experience_variant

        if experience_variant.is_default:
            experience_variant_obj = experience_variants_crud.create_default_variant(
                experience_id=experience_id,
            )
        else:
            experience_variant_obj = experience_variants_crud.create_experience_variant(
                experience_id=experience_id,
                name=experience_variant.name,
                description=experience_variant.description,
            )

            for feature_variant in experience_variant.feature_variants:
                experience_feature_variants_crud.create(
                    {
                        "experience_variant_id": experience_variant_obj.pid,
                        "experience_feature_id": feature_variant.experience_feature_id,
                        "name": feature_variant.name,
                        "config": feature_variant.config,
                    }
                )

        personalisation_experience_variants_crud.create(
            {
                "personalisation_id": personalisation.pid,
                "experience_variant_id": experience_variant_obj.pid,
                "target_percentage": target_percentage,
            }
        )

    # Create personalisation metrics associations
    if selected_metrics:
        for metric_id in selected_metrics:
            personalisation_metrics_crud.create_personalisation_metric(
                personalisation_id=personalisation.pid, metric_id=metric_id
            )
    # Create personalisation-segment rules
    if getattr(personalisation_data, 'segments', None):
        segments_crud = SegmentsCRUD(db)
        seg_rules_crud = PersonalisationSegmentRulesCRUD(db)
        for seg in personalisation_data.segments:
            # validate segment exists and belongs to org/app
            seg_obj = segments_crud.get_by_pid(seg.segment_id)
            if not seg_obj or str(seg_obj.organisation_id) != str(auth.organisation_id) or seg_obj.app_id != auth.app_id:
                raise HTTPException(status_code=400, detail=f"Segment not found or unauthorized: {seg.segment_id}")
            seg_rules_crud.create({
                "personalisation_id": personalisation.pid,
                "segment_id": seg.segment_id,
                "rule_config": seg.rule_config,
            })

    # Return full personalisation with segments, variants, metrics
    return personalisations_crud.get_detailed_personalisation(personalisation.pid)


@router.get("/", response_model=List[PersonalisationListResponse])
async def list_personalisations(
    auth: AuthContext = Depends(require_app_context),
    search: Optional[str] = Query(
        None, description="Search personalisations by name or description"
    ),
    order_by: str = Query(
        "created_at", description="Order by field (created_at, name, status)"
    ),
    order_direction: str = Query("desc", description="Order direction (asc, desc)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    personalisations_crud = PersonalisationsCRUD(db)

    if search:
        personalisations = personalisations_crud.search_personalisations(
            organisation_id=str(auth.organisation_id),
            app_id=auth.app_id,
            search_term=search,
            skip=skip,
            limit=limit,
        )
    else:
        personalisations = personalisations_crud.get_multi_by_org(
            organisation_id=str(auth.organisation_id),
            app_id=auth.app_id,
            skip=skip,
            limit=limit,
            order_by=order_by,
            order_direction=order_direction,
        )

    return personalisations


@router.get(
    "/personalised-experiences/{experience_id}/",
    response_model=List[PersonalisationDetailedResponse],
)
async def list_personalised_experiences(
    experience_id: UUID,
    auth: AuthContext = Depends(require_app_context),
    db: Session = Depends(get_db),
):
    personalisations_crud = PersonalisationsCRUD(db)

    personalisations = personalisations_crud.get_experience_personalisations(
        experience_id=experience_id,
    )

    return personalisations


@router.patch("/{pid}/", response_model=PersonalisationDetailedResponse)
async def update_personalisation(
    pid: UUID,
    update_data: PersonalisationUpdate,
    auth: AuthContext = Depends(require_app_context),
    db: Session = Depends(get_db),
):
    """
    Update a personalisation. By default only new evaluations see changes.
    If reassign=True, existing user assignments for this personalisation will be re-assigned on next request.
    """
    crud = PersonalisationsCRUD(db)

    # fetch and auth
    personalisation = crud.get_detailed_personalisation(pid)

    if not personalisation:
        raise HTTPException(status_code=404, detail="Personalisation not found")

    if str(personalisation.organisation_id) != str(auth.organisation_id):
        raise HTTPException(status_code=403, detail="Not in your organization")

    if personalisation.app_id != auth.app_id:
        raise HTTPException(status_code=403, detail="Not in your app")

    # validate any new variants or metrics here (omitted for brevity)

    try:
        # pass the Pydantic DTO so nested fields remain as objects
        updated = crud.update_personalisation(personalisation, update_data)
        # Sync segment rules
        if update_data.segments is not None:
            segments_crud = SegmentsCRUD(db)
            seg_rules_crud = PersonalisationSegmentRulesCRUD(db)
            # map existing rules
            existing = {str(r.segment_id): r for r in updated.segment_rules}
            # incoming payload
            incoming = {str(s.segment_id): s for s in update_data.segments}
            # update or create
            for seg_id, seg in incoming.items():
                # validate segment exists
                seg_obj = segments_crud.get_by_pid(seg.segment_id)
                if not seg_obj or str(seg_obj.organisation_id) != str(auth.organisation_id) or seg_obj.app_id != auth.app_id:
                    raise HTTPException(status_code=400, detail=f"Segment not found or unauthorized: {seg.segment_id}")
                if seg_id in existing:
                    rule = existing[seg_id]
                    rule.rule_config = seg.rule_config
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(rule, "rule_config")
                else:
                    seg_rules_crud.create({
                        "personalisation_id": updated.pid,
                        "segment_id": seg.segment_id,
                        "rule_config": seg.rule_config,
                    })
            # delete removed
            for seg_id, rule in existing.items():
                if seg_id not in incoming:
                    db.delete(rule)
            db.flush()
            db.refresh(updated)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return updated


@router.get("/{pid}/", response_model=PersonalisationDetailedResponse)
async def get_personalisation(
    pid: UUID,
    auth: AuthContext = Depends(require_app_context),
    db: Session = Depends(get_db),
):
    """
    Get a personalisation by ID with all its details including variants and metrics.
    """
    personalisations_crud = PersonalisationsCRUD(db)

    # Get the personalisation with all related data
    personalisation = personalisations_crud.get_detailed_personalisation(pid)

    if not personalisation:
        raise HTTPException(status_code=404, detail="Personalisation not found")

    # Validate organisation and app access
    if str(personalisation.organisation_id) != str(auth.organisation_id):
        raise HTTPException(status_code=403, detail="Not in your organization")

    if personalisation.app_id != auth.app_id:
        raise HTTPException(status_code=403, detail="Not in your app")

    return personalisation


@router.patch("/{pid}/disable/", response_model=PersonalisationDetailedResponse)
async def disable_personalisation(
    pid: UUID,
    auth: AuthContext = Depends(require_app_context),
    db: Session = Depends(get_db),
):
    """
    Disable a personalisation and remove existing user assignments.
    """
    crud = PersonalisationsCRUD(db)

    # fetch and auth
    personalisation = crud.get_by_pid(pid)

    if not personalisation:
        raise HTTPException(status_code=404, detail="Personalisation not found")

    if str(personalisation.organisation_id) != str(auth.organisation_id):
        raise HTTPException(status_code=403, detail="Not in your organization")

    if personalisation.app_id != auth.app_id:
        raise HTTPException(status_code=403, detail="Not in your app")

    updated = crud.disable_personalisation(personalisation)

    if not updated:
        raise HTTPException(status_code=404, detail="Personalisation not found")

    return updated


@router.patch("/{pid}/enable/", response_model=PersonalisationDetailedResponse)
async def enable_personalisation(
    pid: UUID,
    auth: AuthContext = Depends(require_app_context),
    db: Session = Depends(get_db),
):
    """
    Enable a previously disabled personalisation.
    """
    crud = PersonalisationsCRUD(db)

    # fetch and auth
    personalisation = crud.get_by_pid(pid)

    if not personalisation:
        raise HTTPException(status_code=404, detail="Personalisation not found")

    if str(personalisation.organisation_id) != str(auth.organisation_id):
        raise HTTPException(status_code=403, detail="Not in your organization")

    if personalisation.app_id != auth.app_id:
        raise HTTPException(status_code=403, detail="Not in your app")

    updated = crud.enable_personalisation(personalisation)

    if not updated:
        raise HTTPException(status_code=404, detail="Personalisation not found")

    return updated
