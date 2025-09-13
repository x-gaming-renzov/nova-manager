from typing import Optional, List
from uuid import UUID as UUIDType
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import and_, asc, desc
from sqlalchemy.orm.attributes import flag_modified
from datetime import datetime, timezone

from nova_manager.components.experiences.models import ExperienceVariants
from nova_manager.core.base_crud import BaseCRUD
from nova_manager.components.personalisations.models import (
    PersonalisationExperienceVariants,
    Personalisations,
)
from nova_manager.api.personalisations.request_response import PersonalisationUpdate
from nova_manager.components.metrics.models import PersonalisationMetrics
from nova_manager.components.metrics.crud import PersonalisationMetricsCRUD
from nova_manager.components.experiences.crud import (
    ExperienceVariantsCRUD,
    ExperienceFeatureVariantsCRUD,
)


class PersonalisationsCRUD(BaseCRUD):
    """CRUD operations for Personalisations"""

    def __init__(self, db: Session):
        super().__init__(Personalisations, db)

    def create_personalisation(
        self,
        experience_id: UUIDType,
        organisation_id: str,
        app_id: str,
        name: str,
        description: str,
        priority: int,
        rule_config: dict,
        rollout_percentage: int,
    ) -> Personalisations:
        personalisation = Personalisations(
            experience_id=experience_id,
            organisation_id=organisation_id,
            app_id=app_id,
            name=name,
            description=description,
            priority=priority,
            rule_config=rule_config,
            rollout_percentage=rollout_percentage,
            is_active=True,  # new personalisations enabled by default
        )

        self.db.add(personalisation)
        self.db.flush()
        self.db.refresh(personalisation)

        return personalisation

    def get_by_name(
        self, name: str, experience_id: UUIDType
    ) -> Optional[Personalisations]:
        """Get personalisation by name within an experience"""
        return (
            self.db.query(Personalisations)
            .filter(
                and_(
                    Personalisations.name == name,
                    Personalisations.experience_id == experience_id,
                )
            )
            .first()
        )

    def search_personalisations(
        self,
        organisation_id: str,
        app_id: Optional[str] = None,
        experience_id: Optional[UUIDType] = None,
        search_term: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Personalisations]:
        """Search personalisations with filters"""
        query = (
            self.db.query(Personalisations)
            .options(selectinload(Personalisations.experience))
            .filter(Personalisations.organisation_id == organisation_id)
        )

        if app_id:
            query = query.filter(Personalisations.app_id == app_id)

        if experience_id:
            query = query.filter(Personalisations.experience_id == experience_id)

        if search_term:
            search_pattern = f"%{search_term}%"
            query = query.filter(
                Personalisations.name.ilike(search_pattern)
                | Personalisations.description.ilike(search_pattern)
            )

        return query.offset(offset).limit(limit).all()

    def get_multi_by_org(
        self,
        organisation_id: str,
        app_id: str,
        skip: int = 0,
        limit: int = 100,
        order_by: str = "created_at",
        order_direction: str = "desc",
    ) -> List[Personalisations]:
        """Get multiple personalisations by organisation and optionally app"""
        query = (
            self.db.query(Personalisations)
            .options(selectinload(Personalisations.experience))
            .filter(
                Personalisations.organisation_id == organisation_id,
                Personalisations.app_id == app_id,
            )
        )

        # Apply ordering
        order_column = getattr(Personalisations, order_by, Personalisations.created_at)
        if order_direction.lower() == "desc":
            query = query.order_by(desc(order_column))
        else:
            query = query.order_by(asc(order_column))

        return query.offset(skip).limit(limit).all()

    def get_experience_personalisations(
        self, experience_id: UUIDType
    ) -> List[Personalisations]:
        """Get all personalisations for an experience"""
        from nova_manager.components.personalisations.models import PersonalisationSegmentRules

        return (
            self.db.query(Personalisations)
            .options(
                selectinload(Personalisations.experience_variants)
                .selectinload(PersonalisationExperienceVariants.experience_variant)
                .selectinload(ExperienceVariants.feature_variants),
                selectinload(Personalisations.metrics).selectinload(
                    PersonalisationMetrics.metric
                ),
                selectinload(Personalisations.segment_rules)
                .selectinload(PersonalisationSegmentRules.segment),
            )
            .filter(Personalisations.experience_id == experience_id)
            .all()
        )

    def get_experience_max_priority_personalisation(
        self, experience_id: UUIDType
    ) -> Optional[Personalisations]:
        """Get the max priority personalisation for an experience"""
        return (
            self.db.query(Personalisations)
            .filter(Personalisations.experience_id == experience_id)
            .order_by(desc(Personalisations.priority))
            .first()
        )

    def update_personalisation(
        self,
        personalisation: Personalisations,
        update_data: PersonalisationUpdate,
    ) -> Personalisations:
        """
        Update an existing personalisation.
        Handles updating, adding, or removing experience variants.
        """
        if not personalisation:
            return None

        # Update basic fields if provided
        if update_data.name is not None:
            personalisation.name = update_data.name

        if update_data.description is not None:
            personalisation.description = update_data.description

        if update_data.rule_config is not None:
            personalisation.rule_config = update_data.rule_config
            flag_modified(personalisation, "rule_config")

        if update_data.rollout_percentage is not None:
            personalisation.rollout_percentage = update_data.rollout_percentage

        # Handle experience variants if provided
        if update_data.experience_variants is not None:
            experience_variants_crud = ExperienceVariantsCRUD(self.db)
            experience_feature_variants_crud = ExperienceFeatureVariantsCRUD(self.db)
            personalisation_experience_variants_crud = (
                PersonalisationExperienceVariantsCRUD(self.db)
            )

            # Get existing variant IDs for this personalisation
            existing_variant_ids = {
                str(assoc.experience_variant_id): assoc
                for assoc in personalisation.experience_variants
            }

            updated_variant_ids = set()

            # Process each incoming variant
            for variant_data in update_data.experience_variants:
                if (
                    variant_data.experience_variant.pid
                    and str(variant_data.experience_variant.pid) in existing_variant_ids
                ):
                    # Update existing variant
                    variant_id = str(variant_data.experience_variant.pid)

                    # Get the variant directly
                    association = existing_variant_ids[variant_id]

                    if not association:
                        continue

                    if association:
                        association.target_percentage = variant_data.target_percentage

                    variant = association.experience_variant

                    # Update the variant itself
                    variant.name = variant_data.experience_variant.name
                    variant.description = variant_data.experience_variant.description
                    variant.is_default = variant_data.experience_variant.is_default

                    # Update feature variants
                    if variant_data.experience_variant.feature_variants is not None:
                        experience_variants_crud.update_feature_variants(
                            variant,
                            variant_data.experience_variant.feature_variants,
                        )

                    updated_variant_ids.add(variant_id)
                else:
                    # Create new variant and association using existing CRUD methods
                    if variant_data.experience_variant.is_default:
                        new_variant = experience_variants_crud.create_default_variant(
                            experience_id=personalisation.experience_id
                        )
                    else:
                        new_variant = (
                            experience_variants_crud.create_experience_variant(
                                experience_id=personalisation.experience_id,
                                name=variant_data.experience_variant.name,
                                description=variant_data.experience_variant.description,
                            )
                        )

                        # Create feature variants using existing method
                        if variant_data.experience_variant.feature_variants:
                            for fv in variant_data.experience_variant.feature_variants:
                                experience_feature_variants_crud.create(
                                    {
                                        "experience_variant_id": new_variant.pid,
                                        "experience_feature_id": fv.experience_feature_id,
                                        "name": fv.name,
                                        "config": fv.config,
                                    }
                                )

                    # Create association using existing method
                    personalisation_experience_variants_crud.create(
                        {
                            "personalisation_id": personalisation.pid,
                            "experience_variant_id": new_variant.pid,
                            "target_percentage": variant_data.target_percentage,
                        }
                    )

            # Delete associations for variants not in the update
            for association in personalisation.experience_variants:
                variant_id = str(association.experience_variant_id)
                if variant_id not in updated_variant_ids:
                    self.db.delete(association)

        # Handle metrics if provided
        if update_data.selected_metrics is not None:
            personalisation_metrics_crud = PersonalisationMetricsCRUD(self.db)

            # Get existing metrics for this personalisation
            existing_metrics = personalisation_metrics_crud.get_by_personalisation(
                personalisation.pid
            )
            existing_metric_ids = {str(metric.metric_id) for metric in existing_metrics}
            new_metric_ids = set(update_data.selected_metrics)

            # Delete metrics that are no longer selected
            metrics_to_delete = existing_metric_ids - new_metric_ids
            if metrics_to_delete:
                personalisation_metrics_crud.delete_personalisation_metrics(
                    personalisation.pid, list(metrics_to_delete)
                )

            # Add new metrics that don't already exist
            metrics_to_add = new_metric_ids - existing_metric_ids
            for metric_id in metrics_to_add:
                personalisation_metrics_crud.create_personalisation_metric(
                    personalisation_id=personalisation.pid, metric_id=metric_id
                )

        # If requested, mark existing assignments to be re-evaluated
        if update_data.reassign:
            personalisation.reassign = True

        # bump last_updated_at when variants or metrics changed
        personalisation.last_updated_at = datetime.now(timezone.utc)

        # Persist updates
        self.db.add(personalisation)
        self.db.flush()
        self.db.refresh(personalisation)

        return personalisation

    def get_detailed_personalisation(self, pid: UUIDType) -> Optional[Personalisations]:
        """Get a personalisation by ID with all its relationships loaded"""
        from nova_manager.components.personalisations.models import PersonalisationSegmentRules

        return (
            self.db.query(Personalisations)
            .options(
                selectinload(Personalisations.experience),
                selectinload(Personalisations.experience_variants)
                .selectinload(PersonalisationExperienceVariants.experience_variant)
                .selectinload(ExperienceVariants.feature_variants),
                selectinload(Personalisations.metrics).selectinload(
                    PersonalisationMetrics.metric
                ),
                selectinload(Personalisations.segment_rules)
                .selectinload(PersonalisationSegmentRules.segment),
            )
            .filter(Personalisations.pid == pid)
            .first()
        )

    def disable_personalisation(
        self, personalisation: Personalisations
    ) -> Optional[Personalisations]:
        """Disable a personalisation by pid"""

        personalisation.is_active = False

        # Set reassign to true by default to re-evaluate existing user assignments
        personalisation.reassign = True

        self.db.add(personalisation)
        self.db.flush()
        self.db.refresh(personalisation)

        return personalisation

    def enable_personalisation(
        self, personalisation: Personalisations
    ) -> Optional[Personalisations]:
        """Enable a personalisation by pid"""

        personalisation.is_active = True

        # Set reassign to true by default to re-evaluate existing user assignments
        personalisation.reassign = True

        self.db.add(personalisation)
        self.db.flush()
        self.db.refresh(personalisation)

        return personalisation


class PersonalisationExperienceVariantsCRUD(BaseCRUD):
    def __init__(self, db: Session):
        super().__init__(PersonalisationExperienceVariants, db)
 
class PersonalisationSegmentRulesCRUD(BaseCRUD):
    """CRUD for personalisation-segment rules bridge table"""
    def __init__(self, db: Session):
        from nova_manager.components.personalisations.models import PersonalisationSegmentRules
        super().__init__(PersonalisationSegmentRules, db)
