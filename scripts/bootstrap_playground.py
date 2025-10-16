#!/usr/bin/env python
"""Seed a playground organisation/app with baseline experience and personalisation.

This script is idempotent. Run it to provision the baseline playground data and
print the environment variables needed to enable playground mode.
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Dict, Iterable, Optional, Set

from sqlalchemy import and_
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from nova_manager.database.session import SessionLocal
from nova_manager.core.security import create_sdk_api_key
from nova_manager.components.auth.models import Organisation, App
from nova_manager.components.feature_flags.models import FeatureFlags
from nova_manager.components.experiences.models import (
    Experiences,
    ExperienceFeatures,
    ExperienceVariants,
    ExperienceFeatureVariants,
)
from nova_manager.components.personalisations.crud import PersonalisationsCRUD
from nova_manager.components.personalisations.models import (
    Personalisations,
    PersonalisationExperienceVariants,
)
from nova_manager.components.user_experience.models import UserExperience  # noqa: F401

DEFAULT_ORG_NAME = "Playground Organisation"
DEFAULT_APP_NAME = "Playground App"
DEFAULT_EXPERIENCE_NAME = "VampireSurvivalExperience"
DEFAULT_PERSONALISATION_NAME = "Superman from USA"
DEFAULT_PERSONALISATION_PREFIX = "Playground"
DEFAULT_PERSONALISATION_DESCRIPTION = "Fast progression for US players"
DEFAULT_ROLLOUT = 100
DEFAULT_RULE_CONFIG = {
    "conditions": [
        {
            "field": "country",
            "operator": "equals",
            "value": "United States",
            "type": "text",
        }
    ]
}
DEFAULT_TOKEN_TTL_MINUTES = 24 * 60

STATIC_DIR = Path(__file__).resolve().parents[1] / "nova_manager" / "static"
DEFAULT_EXP_CONFIG_PATH = STATIC_DIR / "exp.json"
DEFAULT_PER_CONFIG_PATH = STATIC_DIR / "per.json"

logger = logging.getLogger("bootstrap_playground")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap playground seed data")
    parser.add_argument("--org-name", default=DEFAULT_ORG_NAME)
    parser.add_argument("--app-name", default=DEFAULT_APP_NAME)
    parser.add_argument("--experience-name", default=DEFAULT_EXPERIENCE_NAME)
    parser.add_argument("--personalisation-name", default=DEFAULT_PERSONALISATION_NAME)
    parser.add_argument(
        "--personalisation-prefix", default=DEFAULT_PERSONALISATION_PREFIX
    )
    parser.add_argument(
        "--experience-config",
        default=str(DEFAULT_EXP_CONFIG_PATH),
        help="Path to experience (exp.json) template",
    )
    parser.add_argument(
        "--personalisation-config",
        default=str(DEFAULT_PER_CONFIG_PATH),
        help="Path to personalisation (per.json) template",
    )
    return parser.parse_args()


def load_json(path: Path) -> Dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def ensure_organisation(session: Session, name: str) -> Organisation:
    organisation = session.query(Organisation).filter_by(name=name).first()
    if organisation:
        logger.info("Organisation '%s' already exists", name)
        return organisation

    organisation = Organisation(name=name)
    session.add(organisation)
    session.flush()
    logger.info("Created organisation '%s'", name)
    return organisation


def ensure_app(session: Session, organisation: Organisation, name: str) -> App:
    app = (
        session.query(App)
        .filter(and_(App.organisation_id == organisation.pid, App.name == name))
        .first()
    )
    if app:
        logger.info("App '%s' already exists", name)
        return app

    app = App(name=name, organisation_id=organisation.pid)
    session.add(app)
    session.flush()
    logger.info("Created app '%s'", name)
    return app


def ensure_feature_flags(
    session: Session,
    organisation_id: str,
    app_id: str,
    objects_config: Dict[str, Dict],
) -> Dict[str, FeatureFlags]:
    feature_flags: Dict[str, FeatureFlags] = {}
    for name, cfg in objects_config.items():
        feature = (
            session.query(FeatureFlags)
            .filter_by(name=name, organisation_id=organisation_id, app_id=app_id)
            .first()
        )
        if feature:
            feature_flags[name] = feature
            continue

        feature = FeatureFlags(
            name=name,
            description=cfg.get("description", ""),
            organisation_id=organisation_id,
            app_id=app_id,
            type=cfg.get("type", ""),
            keys_config=cfg.get("keys", {}),
            is_active=True,
        )
        session.add(feature)
        session.flush()
        feature_flags[name] = feature
        logger.info("Created feature flag '%s'", name)
    return feature_flags


def ensure_experience(
    session: Session,
    organisation_id: str,
    app_id: str,
    experience_name: str,
    experience_cfg: Dict,
) -> Experiences:
    experience = (
        session.query(Experiences)
        .filter_by(
            name=experience_name,
            organisation_id=organisation_id,
            app_id=app_id,
        )
        .first()
    )
    if experience:
        return experience

    experience = Experiences(
        name=experience_name,
        description=experience_cfg.get("description", experience_name),
        status=experience_cfg.get("status", "active"),
        organisation_id=organisation_id,
        app_id=app_id,
    )
    session.add(experience)
    session.flush()
    logger.info("Created experience '%s'", experience_name)
    return experience


def ensure_experience_features(
    session: Session,
    experience: Experiences,
    feature_flags: Dict[str, FeatureFlags],
    attached_objects: Iterable[str],
) -> Dict[str, ExperienceFeatures]:
    feature_map: Dict[str, ExperienceFeatures] = {}
    for feature_name in attached_objects:
        feature_flag = feature_flags.get(feature_name)
        if not feature_flag:
            logger.warning("Skipping unknown feature flag '%s'", feature_name)
            continue

        association = (
            session.query(ExperienceFeatures)
            .filter_by(
                experience_id=experience.pid,
                feature_id=feature_flag.pid,
            )
            .first()
        )
        if association:
            feature_map[feature_name] = association
            continue

        association = ExperienceFeatures(
            experience_id=experience.pid,
            feature_id=feature_flag.pid,
        )
        session.add(association)
        session.flush()
        feature_map[feature_name] = association
        logger.info(
            "Linked feature flag '%s' to experience '%s'", feature_name, experience.name
        )
    return feature_map


def ensure_experience_variant(
    session: Session,
    experience: Experiences,
    variant_name: str,
    description: str,
    is_default: bool,
) -> ExperienceVariants:
    variant = (
        session.query(ExperienceVariants)
        .filter_by(experience_id=experience.pid, name=variant_name)
        .first()
    )
    if variant:
        variant.description = description
        variant.is_default = is_default
        return variant

    variant = ExperienceVariants(
        experience_id=experience.pid,
        name=variant_name,
        description=description,
        is_default=is_default,
    )
    session.add(variant)
    session.flush()
    logger.info(
        "Created experience variant '%s' for experience '%s'",
        variant_name,
        experience.name,
    )
    return variant


def upsert_feature_variant(
    session: Session,
    variant: ExperienceVariants,
    experience_feature: ExperienceFeatures,
    name: str,
    config: Dict,
) -> ExperienceFeatureVariants:
    existing = (
        session.query(ExperienceFeatureVariants)
        .filter_by(
            experience_variant_id=variant.pid,
            experience_feature_id=experience_feature.pid,
        )
        .first()
    )
    if existing:
        existing.name = name
        existing.config = config
        flag_modified(existing, "config")
        return existing

    record = ExperienceFeatureVariants(
        experience_variant_id=variant.pid,
        experience_feature_id=experience_feature.pid,
        name=name,
        config=config,
    )
    session.add(record)
    return record


def ensure_personalisation(
    personalisations_crud: PersonalisationsCRUD,
    experience: Experiences,
    organisation_id: str,
    app_id: str,
    name: str,
    description: str,
    rule_config: Dict,
    rollout_percentage: int,
) -> Personalisations:
    existing = personalisations_crud.get_by_name(name, experience.pid)
    if existing:
        return existing

    max_priority = personalisations_crud.get_experience_max_priority_personalisation(
        experience.pid
    )
    next_priority = (max_priority.priority + 1) if max_priority else 1

    personalisation = personalisations_crud.create_personalisation(
        experience_id=experience.pid,
        organisation_id=organisation_id,
        app_id=app_id,
        name=name,
        description=description,
        priority=next_priority,
        rule_config=rule_config,
        rollout_percentage=rollout_percentage,
    )
    logger.info(
        "Created personalisation '%s' for experience '%s'",
        name,
        experience.name,
    )
    return personalisation


def ensure_personalisation_variant_link(
    session: Session,
    personalisation: Personalisations,
    variant: ExperienceVariants,
    target_percentage: int,
) -> None:
    link = (
        session.query(PersonalisationExperienceVariants)
        .filter_by(
            personalisation_id=personalisation.pid,
            experience_variant_id=variant.pid,
        )
        .first()
    )
    if link:
        link.target_percentage = target_percentage
        return

    session.add(
        PersonalisationExperienceVariants(
            personalisation_id=personalisation.pid,
            experience_variant_id=variant.pid,
            target_percentage=target_percentage,
        )
    )


def resolve_feature_for_variant(
    feature_map: Dict[str, ExperienceFeatures],
    config: Dict,
    already_used: Set[str],
) -> Optional[ExperienceFeatures]:
    config_keys = set(config.keys())
    best_match: Optional[ExperienceFeatures] = None
    best_score = 0

    for feature in feature_map.values():
        feature_id = str(feature.pid)
        if feature_id in already_used:
            continue
        feature_keys = set(feature.feature_flag.keys_config.keys())
        overlap = len(config_keys & feature_keys)
        if overlap > best_score:
            best_score = overlap
            best_match = feature

    if best_match:
        already_used.add(str(best_match.pid))
    return best_match


def bootstrap_playground(args: argparse.Namespace) -> Dict[str, str]:
    exp_cfg = load_json(Path(args.experience_config))
    per_cfg_raw = load_json(Path(args.personalisation_config))

    if not isinstance(per_cfg_raw, list) or not per_cfg_raw:
        raise SystemExit("personalisation config must be a non-empty list")

    personalisation_template = per_cfg_raw[0]
    experience_cfg = exp_cfg.get("experiences", {}).get(args.experience_name)
    if not experience_cfg:
        raise SystemExit(
            f"Experience '{args.experience_name}' missing in experience config file"
        )

    objects_cfg = exp_cfg.get("objects", {})
    attached_objects = [
        name for name, enabled in experience_cfg.get("objects", {}).items() if enabled
    ]

    with SessionLocal() as session:
        with session.begin():
            organisation = ensure_organisation(session, args.org_name)
            app = ensure_app(session, organisation, args.app_name)

            organisation_id = str(organisation.pid)
            app_id = str(app.pid)

            feature_flags = ensure_feature_flags(
                session, organisation_id, app_id, objects_cfg
            )
            experience = ensure_experience(
                session,
                organisation_id,
                app_id,
                args.experience_name,
                experience_cfg,
            )
            experience_features = ensure_experience_features(
                session, experience, feature_flags, attached_objects
            )

            personalisations_crud = PersonalisationsCRUD(session)
            personalisation = ensure_personalisation(
                personalisations_crud,
                experience,
                organisation_id,
                app_id,
                args.personalisation_name,
                personalisation_template.get(
                    "description", DEFAULT_PERSONALISATION_DESCRIPTION
                ),
                personalisation_template.get("rule_config", DEFAULT_RULE_CONFIG),
                personalisation_template.get("rollout_percentage", DEFAULT_ROLLOUT),
            )

            ensure_experience_variant(
                session,
                experience,
                variant_name=f"{experience.name} Default",
                description="Baseline experience",
                is_default=True,
            )

            for variant_entry in personalisation_template.get("experience_variants", []):
                variant_info = variant_entry.get("experience_variant", {})
                variant_name = variant_info.get("name", "Variant")
                variant = ensure_experience_variant(
                    session,
                    experience,
                    variant_name=variant_name,
                    description=variant_info.get(
                        "description", f"Variant for {personalisation.name}"
                    ),
                    is_default=variant_info.get("is_default", False),
                )

                used_features: Set[str] = set()
                for feature_variant in variant_info.get("feature_variants", []):
                    config = feature_variant.get("config", {})
                    if not config:
                        continue
                    matching_feature = resolve_feature_for_variant(
                        experience_features, config, used_features
                    )
                    if not matching_feature:
                        logger.warning(
                            "Could not map feature variant '%s' to a feature flag; skipping",
                            feature_variant.get("name", "unknown"),
                        )
                        continue

                    upsert_feature_variant(
                        session,
                        variant,
                        matching_feature,
                        feature_variant.get("name")
                        or f"{variant.name}::{matching_feature.feature_flag.name}",
                        config,
                    )

                ensure_personalisation_variant_link(
                    session,
                    personalisation,
                    variant,
                    variant_entry.get("target_percentage", DEFAULT_ROLLOUT),
                )

            session.flush()

            return {
                "organisation_id": organisation_id,
                "app_id": app_id,
                "experience_id": str(experience.pid),
                "personalisation_id": str(personalisation.pid),
            }


def main() -> int:
    args = parse_args()
    ids = bootstrap_playground(args)

    sdk_key = create_sdk_api_key(ids["organisation_id"], ids["app_id"])

    print("Playground bootstrap complete!\n")
    print("Set the following environment variables:")
    print("PLAYGROUND_ENABLED=true")
    print(f"PLAYGROUND_ORGANISATION_ID={ids['organisation_id']}")
    print(f"PLAYGROUND_APP_ID={ids['app_id']}")
    print(f"PLAYGROUND_SDK_KEY={sdk_key}")
    print(f"PLAYGROUND_EXPERIENCE_NAME={args.experience_name}")
    print(f"PLAYGROUND_BASE_PERSONALISATION_NAME={args.personalisation_name}")
    print(f"PLAYGROUND_PERSONALISATION_NAME_PREFIX={args.personalisation_prefix}")
    print(
        f"PLAYGROUND_TOKEN_TTL_MINUTES={DEFAULT_TOKEN_TTL_MINUTES}  # adjust as needed"
    )

    print("\nOptional overrides:")
    print(
        "- Use --experience-config / --personalisation-config to point at custom JSON"
    )
    print("- Regenerate SDK key by rerunning the script if desired")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
