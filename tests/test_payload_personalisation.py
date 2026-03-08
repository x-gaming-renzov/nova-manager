"""Tests for runtime context (payload) merging into personalisation rule evaluation.

The payload dict passed in evaluation requests is merged with the stored user_profile
to form the evaluation context for personalisation rules. user_profile takes precedence
over payload for overlapping keys, ensuring stored profile data is authoritative.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from nova_manager.components.rule_evaluator.controller import RuleEvaluator
from nova_manager.flows.get_user_experience_variant_flow_async import (
    GetUserExperienceVariantFlowAsync,
)


# ---------------------------------------------------------------------------
# Helpers to build mock objects
# ---------------------------------------------------------------------------


def _make_user(user_id="player_42", profile=None):
    user = MagicMock()
    user.pid = uuid.uuid4()
    user.user_id = user_id
    user.user_profile = profile if profile is not None else {}
    return user


def _make_feature_flag(name="banner", default_variant=None):
    ff = MagicMock()
    ff.pid = uuid.uuid4()
    ff.name = name
    ff.default_variant = default_variant or {"enabled": False}
    return ff


def _make_experience_feature(feature_flag):
    ef = MagicMock()
    ef.pid = uuid.uuid4()
    ef.feature_flag = feature_flag
    return ef


def _make_feature_variant(experience_feature_id, name="variant_a", config=None):
    fv = MagicMock()
    fv.pid = uuid.uuid4()
    fv.name = name
    fv.experience_feature_id = experience_feature_id
    fv.config = config or {"enabled": True}
    return fv


def _make_experience_variant(feature_variants=None):
    ev = MagicMock()
    ev.pid = uuid.uuid4()
    ev.feature_variants = feature_variants or []
    return ev


def _make_personalisation_experience_variant(
    experience_variant, target_percentage=100
):
    pev = MagicMock()
    pev.pid = uuid.uuid4()
    pev.target_percentage = target_percentage
    pev.experience_variant_id = experience_variant.pid
    pev.experience_variant = experience_variant
    return pev


def _make_personalisation(
    rule_config,
    experience_variants=None,
    is_active=True,
    reassign=False,
    rollout_percentage=100,
    segment_rules=None,
):
    p = MagicMock()
    p.pid = uuid.uuid4()
    p.name = "test-personalisation"
    p.rule_config = rule_config
    p.is_active = is_active
    p.reassign = reassign
    p.rollout_percentage = rollout_percentage
    p.segment_rules = segment_rules or []
    p.experience_variants = experience_variants or []
    p.last_updated_at = None
    return p


def _make_experience(name="tournament-banner", personalisations=None, features=None):
    exp = MagicMock()
    exp.pid = uuid.uuid4()
    exp.name = name
    exp.personalisations = personalisations or []
    exp.features = features or []
    return exp


def _build_experience_with_personalisation(rule_config, reassign=False):
    """Build a complete experience with one personalisation targeting rule_config."""
    ff = _make_feature_flag()
    ef = _make_experience_feature(ff)
    fv = _make_feature_variant(ef.pid)
    ev = _make_experience_variant(feature_variants=[fv])
    pev = _make_personalisation_experience_variant(ev)

    personalisation = _make_personalisation(
        rule_config=rule_config,
        experience_variants=[pev],
        reassign=reassign,
    )

    experience = _make_experience(
        personalisations=[personalisation],
        features=[ef],
    )
    return experience


async def _run_flow(user, experience, payload):
    """Wire up mocks and run the flow for a single experience."""
    db = AsyncMock()
    flow = GetUserExperienceVariantFlowAsync(db)

    flow.users_crud.get_by_user_id = AsyncMock(return_value=user)
    flow.experiences_crud.get_experiences_by_names = AsyncMock(
        return_value=[experience]
    )
    flow.user_experience_personalisation_crud.get_user_experiences_personalisations = (
        AsyncMock(return_value=[])
    )
    flow.user_experience_personalisation_crud.bulk_create_user_experience_personalisations = (
        AsyncMock()
    )

    result = await flow.get_user_experience_variants(
        user_id=user.user_id,
        organisation_id="org-1",
        app_id="app-1",
        payload=payload,
        experience_names=[experience.name],
    )
    return result


# ===========================================================================
# A. RuleEvaluator Unit Tests — Merged Context Sanity
# ===========================================================================


class TestRuleEvaluatorMergedContext:
    """Verify evaluate_rule works correctly with a merged dict."""

    def test_payload_field_matches(self):
        evaluator = RuleEvaluator()
        rule = {
            "conditions": [
                {"field": "in_tournament", "operator": "equals", "value": True}
            ]
        }
        assert evaluator.evaluate_rule(rule, {"in_tournament": True}) is True

    def test_payload_field_does_not_match(self):
        evaluator = RuleEvaluator()
        rule = {
            "conditions": [
                {"field": "in_tournament", "operator": "equals", "value": True}
            ]
        }
        assert evaluator.evaluate_rule(rule, {"in_tournament": False}) is False

    def test_profile_wins_over_payload_via_merge_order(self):
        evaluator = RuleEvaluator()
        rule = {
            "conditions": [
                {"field": "tier", "operator": "equals", "value": "gold"}
            ]
        }
        # Simulates {**payload, **profile} — profile value wins
        merged = {**{"tier": "silver"}, **{"tier": "gold"}}
        assert evaluator.evaluate_rule(rule, merged) is True

    def test_empty_payload_preserves_profile(self):
        evaluator = RuleEvaluator()
        rule = {
            "conditions": [
                {"field": "country", "operator": "equals", "value": "US"}
            ]
        }
        merged = {**{}, **{"country": "US"}}
        assert evaluator.evaluate_rule(rule, merged) is True

    def test_missing_field_returns_false(self):
        evaluator = RuleEvaluator()
        rule = {
            "conditions": [
                {"field": "nonexistent", "operator": "equals", "value": "x"}
            ]
        }
        assert evaluator.evaluate_rule(rule, {"other": "y"}) is False

    def test_multiple_conditions_all_must_match(self):
        evaluator = RuleEvaluator()
        rule = {
            "conditions": [
                {"field": "a", "operator": "equals", "value": 1},
                {"field": "b", "operator": "equals", "value": 2},
            ]
        }
        assert evaluator.evaluate_rule(rule, {"a": 1, "b": 2}) is True
        assert evaluator.evaluate_rule(rule, {"a": 1, "b": 99}) is False

    def test_empty_conditions_returns_false(self):
        evaluator = RuleEvaluator()
        assert evaluator.evaluate_rule({}, {"a": 1}) is False

    def test_various_operators_with_merged_context(self):
        evaluator = RuleEvaluator()
        assert evaluator.evaluate_rule(
            {"conditions": [{"field": "score", "operator": "greater_than", "value": 50}]},
            {"score": 100},
        ) is True
        assert evaluator.evaluate_rule(
            {"conditions": [{"field": "tag", "operator": "in", "value": ["vip", "admin"]}]},
            {"tag": "vip"},
        ) is True
        assert evaluator.evaluate_rule(
            {"conditions": [{"field": "name", "operator": "starts_with", "value": "test"}]},
            {"name": "test_user"},
        ) is True


# ===========================================================================
# B. Happy Path — Flow-level Tests
# ===========================================================================


@pytest.mark.asyncio
class TestPayloadPersonalisationHappyPaths:
    """Happy path scenarios for payload-in-personalisation evaluation."""

    async def test_payload_only_field_matches_personalisation(self):
        """Transient payload field (not in profile) should trigger a personalisation match."""
        user = _make_user(profile={"country": "US"})
        rule = {
            "conditions": [
                {"field": "in_tournament", "operator": "equals", "value": True}
            ]
        }
        experience = _build_experience_with_personalisation(rule)

        result = await _run_flow(user, experience, payload={"in_tournament": True})
        assert result[experience.name].evaluation_reason == "personalisation_match"

    async def test_empty_payload_preserves_existing_behavior(self):
        """Empty payload (default) behaves exactly like before — profile-only evaluation."""
        user = _make_user(profile={"tier": "premium"})
        rule = {
            "conditions": [
                {"field": "tier", "operator": "equals", "value": "premium"}
            ]
        }
        experience = _build_experience_with_personalisation(rule)

        result = await _run_flow(user, experience, payload={})
        assert result[experience.name].evaluation_reason == "personalisation_match"

    async def test_profile_takes_precedence_over_payload(self):
        """When both have the same key, profile value wins."""
        user = _make_user(profile={"tier": "premium"})
        rule = {
            "conditions": [
                {"field": "tier", "operator": "equals", "value": "premium"}
            ]
        }
        experience = _build_experience_with_personalisation(rule)

        # Payload tries to set tier=free; profile's tier=premium should win
        result = await _run_flow(user, experience, payload={"tier": "free"})
        assert result[experience.name].evaluation_reason == "personalisation_match"

    async def test_multiple_conditions_mixed_payload_and_profile(self):
        """Rule with conditions spanning both profile and payload fields should match."""
        user = _make_user(profile={"country": "US"})
        rule = {
            "conditions": [
                {"field": "country", "operator": "equals", "value": "US"},
                {"field": "in_tournament", "operator": "equals", "value": True},
            ]
        }
        experience = _build_experience_with_personalisation(rule)

        result = await _run_flow(
            user, experience, payload={"in_tournament": True}
        )
        assert result[experience.name].evaluation_reason == "personalisation_match"

    async def test_no_personalisations_returns_default_with_payload(self):
        """Experience with no personalisations returns default regardless of payload."""
        user = _make_user(profile={})
        ff = _make_feature_flag()
        ef = _make_experience_feature(ff)
        experience = _make_experience(personalisations=[], features=[ef])

        result = await _run_flow(
            user, experience, payload={"in_tournament": True}
        )
        assert result[experience.name].evaluation_reason == "default_experience"

    async def test_payload_with_numeric_comparison(self):
        """Payload field used with greater_than operator in personalisation rule."""
        user = _make_user(profile={})
        rule = {
            "conditions": [
                {"field": "cart_total", "operator": "greater_than", "value": 100}
            ]
        }
        experience = _build_experience_with_personalisation(rule)

        result = await _run_flow(user, experience, payload={"cart_total": 250})
        assert result[experience.name].evaluation_reason == "personalisation_match"

    async def test_payload_with_in_operator(self):
        """Payload field used with 'in' operator."""
        user = _make_user(profile={})
        rule = {
            "conditions": [
                {"field": "region", "operator": "in", "value": ["NA", "EU", "APAC"]}
            ]
        }
        experience = _build_experience_with_personalisation(rule)

        result = await _run_flow(user, experience, payload={"region": "EU"})
        assert result[experience.name].evaluation_reason == "personalisation_match"

    async def test_payload_with_contains_operator(self):
        """Payload string field used with contains operator."""
        user = _make_user(profile={})
        rule = {
            "conditions": [
                {"field": "page_url", "operator": "contains", "value": "checkout"}
            ]
        }
        experience = _build_experience_with_personalisation(rule)

        result = await _run_flow(
            user, experience, payload={"page_url": "/store/checkout/step-1"}
        )
        assert result[experience.name].evaluation_reason == "personalisation_match"

    async def test_multiple_payload_fields(self):
        """Multiple transient payload fields all evaluated correctly."""
        user = _make_user(profile={})
        rule = {
            "conditions": [
                {"field": "in_tournament", "operator": "equals", "value": True},
                {"field": "tournament_id", "operator": "equals", "value": "spring-2026"},
            ]
        }
        experience = _build_experience_with_personalisation(rule)

        result = await _run_flow(
            user,
            experience,
            payload={"in_tournament": True, "tournament_id": "spring-2026"},
        )
        assert result[experience.name].evaluation_reason == "personalisation_match"


# ===========================================================================
# C. Sad Path — Flow-level Tests
# ===========================================================================


@pytest.mark.asyncio
class TestPayloadPersonalisationSadPaths:
    """Negative / edge-case scenarios for payload-in-personalisation evaluation."""

    async def test_payload_field_no_match_falls_to_default(self):
        """Payload field present but value doesn't match → falls through to default."""
        user = _make_user(profile={})
        rule = {
            "conditions": [
                {"field": "in_tournament", "operator": "equals", "value": True}
            ]
        }
        experience = _build_experience_with_personalisation(rule)

        result = await _run_flow(
            user, experience, payload={"in_tournament": False}
        )
        reason = result[experience.name].evaluation_reason
        assert reason != "personalisation_match"

    async def test_payload_overridden_by_profile_causes_no_match(self):
        """Rule targets payload value, but profile overrides it → no match."""
        user = _make_user(profile={"tier": "free"})
        rule = {
            "conditions": [
                {"field": "tier", "operator": "equals", "value": "premium"}
            ]
        }
        experience = _build_experience_with_personalisation(rule)

        # Payload says premium but profile says free; profile wins → no match
        result = await _run_flow(
            user, experience, payload={"tier": "premium"}
        )
        assert result[experience.name].evaluation_reason != "personalisation_match"

    async def test_missing_payload_field_no_match(self):
        """Rule references a field that exists in neither profile nor payload."""
        user = _make_user(profile={"country": "US"})
        rule = {
            "conditions": [
                {"field": "in_tournament", "operator": "equals", "value": True}
            ]
        }
        experience = _build_experience_with_personalisation(rule)

        result = await _run_flow(user, experience, payload={})
        assert result[experience.name].evaluation_reason != "personalisation_match"

    async def test_none_payload_treated_as_empty(self):
        """payload=None should not crash and behave like empty dict."""
        user = _make_user(profile={"country": "US"})
        rule = {
            "conditions": [
                {"field": "country", "operator": "equals", "value": "US"}
            ]
        }
        experience = _build_experience_with_personalisation(rule)

        result = await _run_flow(user, experience, payload=None)
        assert result[experience.name].evaluation_reason == "personalisation_match"

    async def test_none_user_profile_with_payload(self):
        """user_profile=None should not crash when payload is provided."""
        user = _make_user()
        user.user_profile = None
        rule = {
            "conditions": [
                {"field": "in_tournament", "operator": "equals", "value": True}
            ]
        }
        experience = _build_experience_with_personalisation(rule)

        result = await _run_flow(
            user, experience, payload={"in_tournament": True}
        )
        assert result[experience.name].evaluation_reason == "personalisation_match"

    async def test_both_none_payload_and_profile(self):
        """Both payload=None and user_profile=None → empty context, no match."""
        user = _make_user()
        user.user_profile = None
        rule = {
            "conditions": [
                {"field": "anything", "operator": "equals", "value": True}
            ]
        }
        experience = _build_experience_with_personalisation(rule)

        result = await _run_flow(user, experience, payload=None)
        assert result[experience.name].evaluation_reason != "personalisation_match"

    async def test_partial_condition_match_fails(self):
        """If only one of multiple conditions matches, personalisation should not match."""
        user = _make_user(profile={"country": "US"})
        rule = {
            "conditions": [
                {"field": "country", "operator": "equals", "value": "US"},
                {"field": "in_tournament", "operator": "equals", "value": True},
            ]
        }
        experience = _build_experience_with_personalisation(rule)

        # Only country matches (from profile), in_tournament is missing
        result = await _run_flow(user, experience, payload={})
        assert result[experience.name].evaluation_reason != "personalisation_match"

    async def test_inactive_personalisation_not_evaluated(self):
        """Inactive personalisation should be skipped even if payload matches."""
        user = _make_user(profile={})
        rule = {
            "conditions": [
                {"field": "in_tournament", "operator": "equals", "value": True}
            ]
        }
        ff = _make_feature_flag()
        ef = _make_experience_feature(ff)
        fv = _make_feature_variant(ef.pid)
        ev = _make_experience_variant(feature_variants=[fv])
        pev = _make_personalisation_experience_variant(ev)

        personalisation = _make_personalisation(
            rule_config=rule,
            experience_variants=[pev],
            is_active=False,  # Inactive!
        )
        experience = _make_experience(
            personalisations=[personalisation], features=[ef]
        )

        result = await _run_flow(
            user, experience, payload={"in_tournament": True}
        )
        assert result[experience.name].evaluation_reason != "personalisation_match"

    async def test_numeric_less_than_fails(self):
        """Payload numeric value does not satisfy less_than condition."""
        user = _make_user(profile={})
        rule = {
            "conditions": [
                {"field": "cart_total", "operator": "less_than", "value": 50}
            ]
        }
        experience = _build_experience_with_personalisation(rule)

        result = await _run_flow(user, experience, payload={"cart_total": 100})
        assert result[experience.name].evaluation_reason != "personalisation_match"

    async def test_not_in_operator_fails(self):
        """Payload value that IS in the exclusion list fails not_in."""
        user = _make_user(profile={})
        rule = {
            "conditions": [
                {"field": "region", "operator": "not_in", "value": ["NA", "EU"]}
            ]
        }
        experience = _build_experience_with_personalisation(rule)

        result = await _run_flow(user, experience, payload={"region": "NA"})
        assert result[experience.name].evaluation_reason != "personalisation_match"


# ===========================================================================
# D. Precedence Tests — Exhaustive Key Overlap Scenarios
# ===========================================================================


@pytest.mark.asyncio
class TestPayloadProfilePrecedence:
    """Ensure {**payload, **profile} merge semantics are correct in all cases."""

    async def test_profile_string_beats_payload_string(self):
        user = _make_user(profile={"key": "profile_val"})
        rule = {
            "conditions": [
                {"field": "key", "operator": "equals", "value": "profile_val"}
            ]
        }
        experience = _build_experience_with_personalisation(rule)

        result = await _run_flow(
            user, experience, payload={"key": "payload_val"}
        )
        assert result[experience.name].evaluation_reason == "personalisation_match"

    async def test_profile_int_beats_payload_int(self):
        user = _make_user(profile={"level": 10})
        rule = {
            "conditions": [
                {"field": "level", "operator": "equals", "value": 10}
            ]
        }
        experience = _build_experience_with_personalisation(rule)

        result = await _run_flow(user, experience, payload={"level": 5})
        assert result[experience.name].evaluation_reason == "personalisation_match"

    async def test_profile_bool_beats_payload_bool(self):
        user = _make_user(profile={"active": True})
        rule = {
            "conditions": [
                {"field": "active", "operator": "equals", "value": True}
            ]
        }
        experience = _build_experience_with_personalisation(rule)

        result = await _run_flow(user, experience, payload={"active": False})
        assert result[experience.name].evaluation_reason == "personalisation_match"

    async def test_disjoint_keys_both_available(self):
        """Payload and profile have different keys; both are accessible."""
        user = _make_user(profile={"country": "US"})
        rule = {
            "conditions": [
                {"field": "country", "operator": "equals", "value": "US"},
                {"field": "session_type", "operator": "equals", "value": "mobile"},
            ]
        }
        experience = _build_experience_with_personalisation(rule)

        result = await _run_flow(
            user, experience, payload={"session_type": "mobile"}
        )
        assert result[experience.name].evaluation_reason == "personalisation_match"


# ===========================================================================
# E. Multiple Personalisations — Ordering and Fallthrough
# ===========================================================================


@pytest.mark.asyncio
class TestMultiplePersonalisations:
    """Test evaluation order when multiple personalisations exist."""

    async def test_first_matching_personalisation_wins(self):
        """First personalisation that matches (using payload) should be selected."""
        user = _make_user(profile={})

        ff = _make_feature_flag()
        ef = _make_experience_feature(ff)

        # Personalisation 1: won't match
        fv1 = _make_feature_variant(ef.pid, name="variant_1", config={"v": 1})
        ev1 = _make_experience_variant(feature_variants=[fv1])
        pev1 = _make_personalisation_experience_variant(ev1)
        p1 = _make_personalisation(
            rule_config={
                "conditions": [
                    {"field": "vip", "operator": "equals", "value": True}
                ]
            },
            experience_variants=[pev1],
        )

        # Personalisation 2: will match
        fv2 = _make_feature_variant(ef.pid, name="variant_2", config={"v": 2})
        ev2 = _make_experience_variant(feature_variants=[fv2])
        pev2 = _make_personalisation_experience_variant(ev2)
        p2 = _make_personalisation(
            rule_config={
                "conditions": [
                    {"field": "in_tournament", "operator": "equals", "value": True}
                ]
            },
            experience_variants=[pev2],
        )
        p2.name = "tournament-personalisation"

        experience = _make_experience(
            personalisations=[p1, p2], features=[ef]
        )

        result = await _run_flow(
            user, experience, payload={"in_tournament": True}
        )
        assignment = result[experience.name]
        assert assignment.evaluation_reason == "personalisation_match"
        assert assignment.personalisation_name == "tournament-personalisation"

    async def test_no_personalisations_match_returns_default(self):
        """When no personalisation matches, fallback to default."""
        user = _make_user(profile={})

        ff = _make_feature_flag()
        ef = _make_experience_feature(ff)

        fv = _make_feature_variant(ef.pid)
        ev = _make_experience_variant(feature_variants=[fv])
        pev = _make_personalisation_experience_variant(ev)
        p = _make_personalisation(
            rule_config={
                "conditions": [
                    {"field": "vip", "operator": "equals", "value": True}
                ]
            },
            experience_variants=[pev],
        )

        experience = _make_experience(
            personalisations=[p], features=[ef]
        )

        result = await _run_flow(user, experience, payload={"other": "val"})
        reason = result[experience.name].evaluation_reason
        assert "error" in reason or "default" in reason


# ===========================================================================
# F. Segment Rules + Payload Interaction
# ===========================================================================


@pytest.mark.asyncio
class TestSegmentRulesAndPayload:
    """Segment rules evaluate against payload (already existing behavior).
    Personalisation rules now also evaluate against merged context.
    Both must pass for a personalisation to match."""

    async def test_segment_passes_personalisation_uses_payload(self):
        """Segment rule passes (payload), personalisation rule also uses payload field."""
        user = _make_user(profile={})

        ff = _make_feature_flag()
        ef = _make_experience_feature(ff)
        fv = _make_feature_variant(ef.pid)
        ev = _make_experience_variant(feature_variants=[fv])
        pev = _make_personalisation_experience_variant(ev)

        segment_rule = MagicMock()
        segment_rule.rule_config = {
            "conditions": [
                {"field": "region", "operator": "equals", "value": "NA"}
            ]
        }

        personalisation = _make_personalisation(
            rule_config={
                "conditions": [
                    {"field": "in_tournament", "operator": "equals", "value": True}
                ]
            },
            experience_variants=[pev],
            segment_rules=[segment_rule],
        )

        experience = _make_experience(
            personalisations=[personalisation], features=[ef]
        )

        result = await _run_flow(
            user,
            experience,
            payload={"region": "NA", "in_tournament": True},
        )
        assert result[experience.name].evaluation_reason == "personalisation_match"

    async def test_segment_fails_personalisation_not_evaluated(self):
        """Segment rule fails → personalisation is skipped even if rule would match."""
        user = _make_user(profile={})

        ff = _make_feature_flag()
        ef = _make_experience_feature(ff)
        fv = _make_feature_variant(ef.pid)
        ev = _make_experience_variant(feature_variants=[fv])
        pev = _make_personalisation_experience_variant(ev)

        segment_rule = MagicMock()
        segment_rule.rule_config = {
            "conditions": [
                {"field": "region", "operator": "equals", "value": "EU"}
            ]
        }

        personalisation = _make_personalisation(
            rule_config={
                "conditions": [
                    {"field": "in_tournament", "operator": "equals", "value": True}
                ]
            },
            experience_variants=[pev],
            segment_rules=[segment_rule],
        )

        experience = _make_experience(
            personalisations=[personalisation], features=[ef]
        )

        result = await _run_flow(
            user,
            experience,
            payload={"region": "NA", "in_tournament": True},
        )
        assert result[experience.name].evaluation_reason != "personalisation_match"
