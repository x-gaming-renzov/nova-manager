from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from uuid import UUID, uuid4

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from nova_manager.components.experiences.crud import (
    ExperienceFeatureVariantsCRUD,
    ExperienceVariantsCRUD,
    ExperiencesCRUD,
)
from nova_manager.components.metrics.crud import PersonalisationMetricsCRUD
from nova_manager.components.personalisations.crud import (
    PersonalisationExperienceVariantsCRUD,
    PersonalisationSegmentRulesCRUD,
    PersonalisationsCRUD,
)
from nova_manager.components.personalisations.models import Personalisations
from nova_manager.components.playground.crud import PlaygroundSessionsCRUD
from nova_manager.components.playground.models import PlaygroundSessions
from nova_manager.components.users.models import Users
from nova_manager.core.config import (
    PLAYGROUND_APP_ID,
    PLAYGROUND_BASE_PERSONALISATION_NAME,
    PLAYGROUND_DEFAULT_USER_PROFILE,
    PLAYGROUND_ENABLED,
    PLAYGROUND_EXPERIENCE_NAME,
    PLAYGROUND_ORGANISATION_ID,
    PLAYGROUND_PERSONALISATION_NAME_PREFIX,
    PLAYGROUND_SDK_KEY,
    PLAYGROUND_TOKEN_TTL_MINUTES,
)
from nova_manager.core.security import create_playground_session_token


class PlaygroundConfigurationError(RuntimeError):
    """Raised when playground configuration is incomplete."""


class PlaygroundService:
    """Service orchestration for creating and managing playground sessions."""

    def __init__(self, db: Session):
        self.db = db
        self.personalisations_crud = PersonalisationsCRUD(db)
        self.experiences_crud = ExperiencesCRUD(db)
        self.experience_variants_crud = ExperienceVariantsCRUD(db)
        self.experience_feature_variants_crud = ExperienceFeatureVariantsCRUD(db)
        self.personalisation_experience_variants_crud = (
            PersonalisationExperienceVariantsCRUD(db)
        )
        self.personalisation_segment_rules_crud = PersonalisationSegmentRulesCRUD(db)
        self.personalisation_metrics_crud = PersonalisationMetricsCRUD(db)
        self.sessions_crud = PlaygroundSessionsCRUD(db)

    def create_session(self) -> Dict[str, object]:
        """Create a playground session with cloned personalisation and return auth artifacts."""

        if not self._playground_available():
            raise PlaygroundConfigurationError("Playground configuration is incomplete")

        baseline_personalisation = self._get_baseline_personalisation()

        session_suffix = uuid4().hex[:8]

        cloned_personalisation = self._clone_personalisation(
            baseline_personalisation, session_suffix
        )

        playground_user = self._create_session_user(session_suffix)

        expires_at = self._build_expiry()
        session_record = self.sessions_crud.create_session(
            organisation_id=cloned_personalisation.organisation_id,
            app_id=cloned_personalisation.app_id,
            personalisation_id=cloned_personalisation.pid,
            user_id=playground_user.pid,
            sdk_key=PLAYGROUND_SDK_KEY,
            session_marker=session_suffix,
            expires_at=expires_at,
        )

        token = create_playground_session_token(
            session_id=session_record.pid,
            organisation_id=cloned_personalisation.organisation_id,
            app_id=cloned_personalisation.app_id,
            personalisation_id=cloned_personalisation.pid,
            user_id=playground_user.pid,
            sdk_key=PLAYGROUND_SDK_KEY,
            expires_at=expires_at,
        )

        detailed_personalisation = self.personalisations_crud.get_detailed_personalisation(
            cloned_personalisation.pid
        )

        return {
            "session": session_record,
            "personalisation": detailed_personalisation,
            "token": token,
            "sdk_key": PLAYGROUND_SDK_KEY,
            "user": playground_user,
        }

    def get_session_personalisation(self, session_id: UUID) -> Personalisations | None:
        session = self.sessions_crud.get_by_pid(session_id)
        if not session:
            return None

        return self.personalisations_crud.get_detailed_personalisation(
            session.personalisation_id
        )

    def get_session(self, session_id: UUID) -> PlaygroundSessions | None:
        return self.sessions_crud.get_by_pid(session_id)

    def _playground_available(self) -> bool:
        required = [
            PLAYGROUND_ENABLED,
            PLAYGROUND_ORGANISATION_ID,
            PLAYGROUND_APP_ID,
            PLAYGROUND_SDK_KEY,
            PLAYGROUND_EXPERIENCE_NAME,
            PLAYGROUND_BASE_PERSONALISATION_NAME,
        ]
        return all(required)

    def _get_baseline_personalisation(self) -> Personalisations:
        experience = self.experiences_crud.get_by_name(
            name=PLAYGROUND_EXPERIENCE_NAME,
            organisation_id=PLAYGROUND_ORGANISATION_ID,
            app_id=PLAYGROUND_APP_ID,
        )
        if not experience:
            raise PlaygroundConfigurationError(
                "Playground experience not found for configured organisation/app"
            )

        baseline = self.personalisations_crud.get_by_name(
            name=PLAYGROUND_BASE_PERSONALISATION_NAME,
            experience_id=experience.pid,
        )
        if not baseline:
            raise PlaygroundConfigurationError(
                "Baseline personalisation not found for playground experience"
            )

        detailed = self.personalisations_crud.get_detailed_personalisation(baseline.pid)
        if not detailed:
            raise PlaygroundConfigurationError(
                "Unable to load baseline personalisation details"
            )

        return detailed

    def _clone_personalisation(
        self, personalisation: Personalisations, suffix: str
    ) -> Personalisations:
        cloned_name = self._generate_personalisation_name(
            personalisation.name, personalisation.experience_id, suffix
        )
        cloned_priority = self._generate_priority(personalisation.experience_id)

        rule_config = deepcopy(personalisation.rule_config or {})
        if not isinstance(rule_config, dict):
            rule_config = {}

        conditions = rule_config.get("conditions") or []
        if not isinstance(conditions, list):
            conditions = []

        conditions = [*conditions]
        conditions.append(
            {
                "field": "playground_session_id",
                "operator": "equals",
                "value": suffix,
                "type": "text",
            }
        )
        rule_config["conditions"] = conditions

        clone = Personalisations(
            experience_id=personalisation.experience_id,
            organisation_id=personalisation.organisation_id,
            app_id=personalisation.app_id,
            name=cloned_name,
            description=personalisation.description,
            priority=cloned_priority,
            rule_config=rule_config,
            rollout_percentage=personalisation.rollout_percentage,
            is_active=True,
        )

        self.db.add(clone)
        self.db.flush()
        self.db.refresh(clone)

        for association in personalisation.experience_variants:
            variant = association.experience_variant
            new_variant_name = self._generate_variant_name(
                variant.name, variant.experience_id, suffix
            )
            new_variant = self.experience_variants_crud.create_experience_variant(
                experience_id=variant.experience_id,
                name=new_variant_name,
                description=variant.description,
                is_default=variant.is_default,
            )

            for feature_variant in variant.feature_variants:
                self.experience_feature_variants_crud.create(
                    {
                        "experience_variant_id": new_variant.pid,
                        "experience_feature_id": feature_variant.experience_feature_id,
                        "name": feature_variant.name,
                        "config": deepcopy(feature_variant.config or {}),
                    }
                )

            self.personalisation_experience_variants_crud.create(
                {
                    "personalisation_id": clone.pid,
                    "experience_variant_id": new_variant.pid,
                    "target_percentage": association.target_percentage,
                }
            )

        if personalisation.segment_rules:
            for segment_rule in personalisation.segment_rules:
                self.personalisation_segment_rules_crud.create(
                    {
                        "personalisation_id": clone.pid,
                        "segment_id": segment_rule.segment_id,
                        "rule_config": deepcopy(segment_rule.rule_config or {}),
                    }
                )

        if personalisation.metrics:
            for metric in personalisation.metrics:
                self.personalisation_metrics_crud.create_personalisation_metric(
                    personalisation_id=clone.pid, metric_id=metric.metric_id
                )

        return self.ensure_session_rule(clone, suffix)

    def ensure_session_rule(
        self, personalisation: Personalisations, marker: str
    ) -> Personalisations:
        rule_config = deepcopy(personalisation.rule_config or {})
        if not isinstance(rule_config, dict):
            rule_config = {}

        conditions = rule_config.get("conditions") or []
        if not isinstance(conditions, list):
            conditions = []

        updated = False
        for condition in conditions:
            if condition.get("field") == "playground_session_id":
                condition["value"] = marker
                updated = True
                break

        if not updated:
            conditions.append(
                {
                    "field": "playground_session_id",
                    "operator": "equals",
                    "value": marker,
                    "type": "text",
                }
            )

        rule_config["conditions"] = conditions
        personalisation.rule_config = rule_config
        flag_modified(personalisation, "rule_config")

        self.db.add(personalisation)
        self.db.flush()
        self.db.refresh(personalisation)

        return personalisation

    def _create_session_user(self, suffix: str) -> Users:
        profile = deepcopy(PLAYGROUND_DEFAULT_USER_PROFILE or {})
        profile["playground_session_id"] = suffix
        user_identifier = f"playground-{suffix}"

        user = Users(
            organisation_id=PLAYGROUND_ORGANISATION_ID,
            app_id=PLAYGROUND_APP_ID,
            user_id=user_identifier,
            user_profile=profile,
        )

        self.db.add(user)
        self.db.flush()
        self.db.refresh(user)
        return user

    def _generate_personalisation_name(
        self, base_name: str, experience_id: UUID, suffix: str
    ) -> str:
        candidate = f"{PLAYGROUND_PERSONALISATION_NAME_PREFIX} {suffix}".strip()
        if not candidate:
            candidate = f"{base_name} ({suffix})"

        while self.personalisations_crud.get_by_name(candidate, experience_id):
            candidate = f"{PLAYGROUND_PERSONALISATION_NAME_PREFIX} {uuid4().hex[:6]}"
        return candidate

    def _generate_variant_name(
        self, base_name: str, experience_id: UUID, suffix: str
    ) -> str:
        candidate_suffix = suffix or uuid4().hex[:6]

        while True:
            candidate = f"{base_name} {candidate_suffix}".strip()
            if not self.experience_variants_crud.get_by_name(candidate, experience_id):
                return candidate
            candidate_suffix = uuid4().hex[:6]

    def _generate_priority(self, experience_id: UUID) -> int:
        max_priority = self.db.query(Personalisations.priority).filter(
            Personalisations.experience_id == experience_id
        ).order_by(Personalisations.priority.desc()).first()
        next_priority = (max_priority[0] if max_priority else 0) + 1
        return next_priority

    def _build_expiry(self) -> Optional[datetime]:
        if PLAYGROUND_TOKEN_TTL_MINUTES <= 0:
            return None
        return datetime.now(timezone.utc) + timedelta(minutes=PLAYGROUND_TOKEN_TTL_MINUTES)
