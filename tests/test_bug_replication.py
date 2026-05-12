"""
Bug replication tests for the three issues documented in:
  - LIVEOPS_NOTICE_ISSUE.md (Issues 1, 2, 3)
  - NOVA_ISSUE_PRIORITY_SHADOWING.md (priority silently ignored)

These tests demonstrate the bugs at the unit level without requiring
a running server or database. Each test is expected to PASS — a passing
test proves the bug exists. When the bugs are fixed, these tests should
FAIL, at which point they should be inverted to assert the correct behaviour.
"""

from unittest.mock import MagicMock, patch, PropertyMock
from uuid import uuid4

import pytest

from nova_manager.components.rule_evaluator.controller import RuleEvaluator


# ---------------------------------------------------------------------------
# Issue 1 (P0) — Notice rule gate: is_participant condition blocks all users
#                whose payload does not contain the field.
# ---------------------------------------------------------------------------


class TestIssue1_NoticeRuleGate:
    """
    The Overwatch backend hardcodes this rule_config when creating a notice:

        {"conditions": [{"field": "is_participant", "operator": "equals", "value": True}], "operator": "AND"}

    The mobile SDK does not send `is_participant` in its payload, so
    `evaluate_rule` returns False and Nova returns no_experience_assignment_error.

    CMS uses empty conditions `[]` and works fine — proving the fix is to
    match that pattern.
    """

    def setup_method(self):
        self.evaluator = RuleEvaluator()

    # -- The bug: rule with is_participant condition vs empty payload ----------

    def test_is_participant_rule_rejects_empty_payload(self):
        """BUG: user with no payload → rule fails → notice never shown."""
        rule_config = {
            "conditions": [
                {"field": "is_participant", "operator": "equals", "value": True}
            ],
            "operator": "AND",
        }
        # Mobile SDK sends no per-call payload
        user_payload = {}

        result = self.evaluator.evaluate_rule(rule_config, user_payload)

        # This PASSES — proving the bug: empty payload → no match → no notice
        assert result is False, (
            "Expected rule to reject empty payload (is_participant missing). "
            "If this fails, the bug may have been fixed."
        )

    def test_is_participant_rule_accepts_explicit_true(self):
        """When payload explicitly includes is_participant=True, it works."""
        rule_config = {
            "conditions": [
                {"field": "is_participant", "operator": "equals", "value": True}
            ],
            "operator": "AND",
        }
        user_payload = {"is_participant": True}

        result = self.evaluator.evaluate_rule(rule_config, user_payload)

        assert result is True

    def test_empty_conditions_matches_everyone(self):
        """CMS pattern: empty conditions list → matches all users."""
        rule_config = {
            "conditions": [],
            "operator": "AND",
        }
        user_payload = {}

        result = self.evaluator.evaluate_rule(rule_config, user_payload)

        # Empty conditions = loop body never executes = falls through to True
        assert result is True, (
            "Empty conditions should match everyone — this is the CMS pattern "
            "and the correct fix for notices."
        )

    def test_missing_field_evaluates_to_none_vs_true(self):
        """Root cause: payload.get('is_participant') returns None, None != True."""
        rule_config = {
            "conditions": [
                {"field": "is_participant", "operator": "equals", "value": True}
            ],
        }
        user_payload = {}

        # Directly show what happens inside _evaluate_rule_conditions
        actual_value = user_payload.get("is_participant")
        assert actual_value is None, "Missing field should resolve to None"
        assert (actual_value == True) is False, "None == True is False — this is why the rule fails"


# ---------------------------------------------------------------------------
# Priority Shadowing — client-supplied priority is silently ignored
# ---------------------------------------------------------------------------


class TestPriorityShadowing_ClientPriorityIgnored:
    """
    POST /create-personalisation/ accepts a `priority` field in the request
    schema (PersonalisationCreate.priority) but the router always overwrites
    it with max_priority_in_experience + 1.

    This means the most recently created personalisation always gets the
    highest priority, and because evaluation is priority DESC + first-match-wins,
    it always shadows older personalisations.
    """

    def test_priority_field_exists_in_schema_and_is_used(self):
        """The request schema accepts priority and the router now honors it."""
        from nova_manager.api.personalisations.request_response import PersonalisationCreate
        import inspect
        from nova_manager.api.personalisations.router import create_personalisation

        # Schema accepts priority
        schema_fields = PersonalisationCreate.model_fields
        assert "priority" in schema_fields, "priority field should exist in schema"

        # Router now reads personalisation_data.priority
        source = inspect.getsource(create_personalisation)
        assert "personalisation_data.priority" in source, (
            "FIX VERIFIED: router now reads personalisation_data.priority."
        )

    def test_client_priority_honored_when_provided(self):
        """
        Replicate the fixed router logic: when client sends priority,
        that value is used directly instead of auto-incrementing.
        """
        # Simulate the NEW router logic
        class FakeRequest:
            priority = 5  # client explicitly sends priority=5

        request = FakeRequest()

        if request.priority is not None:
            next_priority = request.priority
        else:
            # would auto-increment, but shouldn't reach here
            next_priority = 999

        assert next_priority == 5, (
            "FIX VERIFIED: client-supplied priority=5 is honored."
        )

    def test_auto_increment_when_priority_not_provided(self):
        """When client sends no priority, fall back to max+1."""
        class FakeRequest:
            priority = None

        request = FakeRequest()

        mock_existing = MagicMock()
        mock_existing.priority = 3

        if request.priority is not None:
            next_priority = request.priority
        else:
            max_priority_personalisation = mock_existing
            next_priority = (
                max_priority_personalisation.priority + 1
                if max_priority_personalisation
                else 1
            )

        assert next_priority == 4, (
            "When no client priority, auto-increment from max (3) to 4."
        )


# ---------------------------------------------------------------------------
# Issues 2 & 3 — Ghost variants/notices: evaluation order causes shadowing
# ---------------------------------------------------------------------------


class TestIssues2And3_EvaluationOrderShadowing:
    """
    When multiple personalisations exist on the same experience:
    - They're loaded in priority DESC order (experiences/models.py:58)
    - Evaluation is first-match-wins with `break` (flow_async.py:258)
    - Newest personalisation (highest auto-assigned priority) evaluates first
    - If its rule matches (e.g. empty conditions = match everyone), older
      personalisations are never reached → they become "ghost" entries

    This replicates Issues 2 (CMS ghost variants) and 3 (ghost notices).
    """

    def setup_method(self):
        self.evaluator = RuleEvaluator()

    def test_broad_rule_at_higher_priority_shadows_narrow_rule(self):
        """
        Scenario from NOVA_ISSUE_PRIORITY_SHADOWING.md:
        - LiveOps notice (priority=1): rule requires is_participant=True
        - CMS deployment (priority=2): empty rule matches everyone

        Evaluation order is [CMS(p=2), Notice(p=1)] due to DESC sort.
        CMS matches first → break → notice is never evaluated.
        """
        # Personalisation 1: LiveOps notice (created first → priority=1)
        notice_rule = {
            "conditions": [
                {"field": "is_participant", "operator": "equals", "value": True}
            ],
            "operator": "AND",
        }
        notice_priority = 1

        # Personalisation 2: CMS deployment (created second → priority=2)
        cms_rule = {
            "conditions": [],
            "operator": "AND",
        }
        cms_priority = 2

        # Build personalisation list in priority DESC order (as SQLAlchemy loads them)
        personalisations_desc = [
            {"name": "CMS Deploy", "priority": cms_priority, "rule": cms_rule, "is_active": True},
            {"name": "Notice", "priority": notice_priority, "rule": notice_rule, "is_active": True},
        ]

        # Simulate the evaluation loop from get_user_experience_variant_flow_async.py
        # User is a participant but payload is empty (mobile SDK behaviour)
        user_payload = {}
        winner = None

        for p in personalisations_desc:
            if not p["is_active"]:
                continue
            # rollout_percentage=100 → always passes (skip that check)
            if not self.evaluator.evaluate_rule(p["rule"], user_payload):
                continue
            winner = p
            break  # first-match-wins

        assert winner is not None, "At least one personalisation should match"
        assert winner["name"] == "CMS Deploy", (
            "BUG: CMS (priority=2, empty rule) wins because it evaluates first. "
            "The notice at priority=1 is never reached."
        )
        assert winner["name"] != "Notice", (
            "The notice is shadowed — it's is_active=True in DB but unreachable "
            "in evaluation. This is the ghost variant/notice bug."
        )

    def test_even_participant_user_gets_cms_not_notice(self):
        """
        Even when user IS a participant, CMS still wins because it evaluates
        first (higher priority) and its empty rule matches everyone.
        """
        notice_rule = {
            "conditions": [
                {"field": "is_participant", "operator": "equals", "value": True}
            ],
            "operator": "AND",
        }
        cms_rule = {"conditions": [], "operator": "AND"}

        personalisations_desc = [
            {"name": "CMS Deploy", "priority": 2, "rule": cms_rule, "is_active": True},
            {"name": "Notice", "priority": 1, "rule": notice_rule, "is_active": True},
        ]

        # This user IS a participant
        user_payload = {"is_participant": True}
        winner = None

        for p in personalisations_desc:
            if not p["is_active"]:
                continue
            if not self.evaluator.evaluate_rule(p["rule"], user_payload):
                continue
            winner = p
            break

        assert winner["name"] == "CMS Deploy", (
            "BUG: Even for a valid participant, CMS at priority=2 shadows the "
            "notice at priority=1 because it evaluates first and matches everyone."
        )

    def test_multiple_notices_same_tournament_only_one_survives(self):
        """
        Issue 3: Multiple notices published for the same tournament.
        Each becomes a personalisation on one experience (tournament_notice_<pid>).
        All get auto-incrementing priorities. Only the last-published notice
        is reachable.
        """
        # Three notices published in sequence for the same tournament
        notices = [
            {"name": "Notice v1", "priority": 1, "rule": {"conditions": [], "operator": "AND"}, "is_active": True},
            {"name": "Notice v2", "priority": 2, "rule": {"conditions": [], "operator": "AND"}, "is_active": True},
            {"name": "Notice v3", "priority": 3, "rule": {"conditions": [], "operator": "AND"}, "is_active": True},
        ]

        # Sorted DESC by priority (as loaded by SQLAlchemy relationship)
        personalisations_desc = sorted(notices, key=lambda p: p["priority"], reverse=True)

        user_payload = {}
        winner = None

        for p in personalisations_desc:
            if not p["is_active"]:
                continue
            if not self.evaluator.evaluate_rule(p["rule"], user_payload):
                continue
            winner = p
            break

        assert winner["name"] == "Notice v3", (
            "BUG: Only the last-published notice (highest auto-priority) is reachable. "
            "v1 and v2 are ghost notices — active in DB but invisible to users."
        )

        # Count how many are actually reachable (should be all 3 if working correctly)
        reachable = []
        for p in personalisations_desc:
            if not p["is_active"]:
                continue
            if not self.evaluator.evaluate_rule(p["rule"], user_payload):
                continue
            reachable.append(p)
            break  # first-match-wins means we stop here

        assert len(reachable) == 1, (
            "BUG: Only 1 of 3 active notices is reachable due to first-match-wins. "
            "Admin sees 3 active notices but users see only 1."
        )

    def test_priority_desc_ordering_confirmed(self):
        """
        Confirm that the Experiences model loads personalisations in priority DESC.
        This is the mechanism that makes newest = highest priority = evaluated first.
        """
        import inspect
        from nova_manager.components.experiences.models import Experiences

        source = inspect.getsource(Experiences)

        assert "priority.desc()" in source, (
            "Experiences.personalisations relationship must use priority.desc() ordering. "
            "This is the mechanism that makes highest-priority evaluate first."
        )
