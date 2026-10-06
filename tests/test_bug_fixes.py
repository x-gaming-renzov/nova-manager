import inspect
import uuid
import pytest
from collections import Counter
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from nova_manager.components.rule_evaluator.controller import RuleEvaluator
from nova_manager.flows.get_user_experience_variant_flow_async import (
    GetUserExperienceVariantFlowAsync,
)


# ────────────────────────────────────────────────────────────────────
# Bug 1: Rule evaluator crashes / gives wrong results with None values
# ────────────────────────────────────────────────────────────────────


class TestRuleEvaluatorNoneHandling:
    """When a user profile field is missing, payload.get(field) returns None.
    Comparison operators must not crash (TypeError) and string operators
    must not match against the literal string "None".
    """

    @pytest.fixture
    def evaluator(self):
        return RuleEvaluator()

    @pytest.mark.parametrize("operator", [
        "greater_than",
        "less_than",
        "greater_than_or_equal",
        "less_than_or_equal",
    ])
    def test_comparison_operators_return_false_on_none(self, evaluator, operator):
        """None compared with >, <, >=, <= must return False, not raise TypeError."""
        result = evaluator._evaluate_condition(None, operator, 18)
        assert result is False

    @pytest.mark.parametrize("operator", [
        "greater_than",
        "less_than",
        "greater_than_or_equal",
        "less_than_or_equal",
    ])
    def test_comparison_operators_do_not_raise_on_none(self, evaluator, operator):
        """Verify no TypeError is raised (the original bug)."""
        # This should not raise
        evaluator._evaluate_condition(None, operator, 42)

    def test_contains_does_not_match_none_string(self, evaluator):
        """'one' in str(None) == 'one' in 'None' == True — this was the bug."""
        result = evaluator._evaluate_condition(None, "contains", "one")
        assert result is False

    def test_starts_with_does_not_match_none_string(self, evaluator):
        """str(None).startswith('No') == True — this was the bug."""
        result = evaluator._evaluate_condition(None, "starts_with", "No")
        assert result is False

    def test_ends_with_does_not_match_none_string(self, evaluator):
        """str(None).endswith('ne') == True — this was the bug."""
        result = evaluator._evaluate_condition(None, "ends_with", "ne")
        assert result is False

    def test_evaluate_rule_with_missing_field(self, evaluator):
        """Full rule evaluation with a missing field should return False, not crash."""
        rule_config = {
            "conditions": [
                {"field": "age", "operator": "greater_than", "value": 18}
            ]
        }
        payload = {"name": "John"}  # no 'age' field

        result = evaluator.evaluate_rule(rule_config, payload)
        assert result is False

    def test_comparison_operators_still_work_with_values(self, evaluator):
        """Non-None values should still compare correctly."""
        assert evaluator._evaluate_condition(25, "greater_than", 18) is True
        assert evaluator._evaluate_condition(10, "greater_than", 18) is False
        assert evaluator._evaluate_condition(5, "less_than", 10) is True
        assert evaluator._evaluate_condition(18, "greater_than_or_equal", 18) is True
        assert evaluator._evaluate_condition(17, "less_than_or_equal", 18) is True

    def test_string_operators_still_work_with_values(self, evaluator):
        """Non-None values should still match correctly."""
        assert evaluator._evaluate_condition("hello world", "contains", "world") is True
        assert evaluator._evaluate_condition("hello", "starts_with", "hel") is True
        assert evaluator._evaluate_condition("hello", "ends_with", "llo") is True


# ────────────────────────────────────────────────────────────────────
# Bug 2: Assignment cache logic — inverted condition + broken continue
# ────────────────────────────────────────────────────────────────────


class TestAssignmentCacheLogic:
    """The cache should be used when the assignment is fresh OR when
    reassign is disabled. The original code only matched stale+no-reassign,
    missing the fresh cache case entirely. Also, `continue` was wrong —
    needed `break` to exit the inner loop + set experience_variant_assignment.
    """

    def _should_use_cache(self, assigned_at, last_updated_at, reassign):
        """Mirrors the fixed condition from get_user_experience_variant_flow_async.py:145"""
        return assigned_at >= last_updated_at or not reassign

    def test_fresh_cache_reassign_false_uses_cache(self):
        """Fresh cache (assigned after update), reassign=False → use cache."""
        assigned_at = datetime(2026, 4, 20)
        last_updated_at = datetime(2026, 4, 15)
        assert self._should_use_cache(assigned_at, last_updated_at, reassign=False) is True

    def test_fresh_cache_reassign_true_uses_cache(self):
        """Fresh cache (assigned after update), reassign=True → use cache.
        Even with reassign=True, if cache is fresh there's nothing new to evaluate.
        """
        assigned_at = datetime(2026, 4, 20)
        last_updated_at = datetime(2026, 4, 15)
        assert self._should_use_cache(assigned_at, last_updated_at, reassign=True) is True

    def test_stale_cache_reassign_false_uses_cache(self):
        """Stale cache, reassign=False → use cache (don't reassign existing users)."""
        assigned_at = datetime(2026, 4, 10)
        last_updated_at = datetime(2026, 4, 15)
        assert self._should_use_cache(assigned_at, last_updated_at, reassign=False) is True

    def test_stale_cache_reassign_true_reevaluates(self):
        """Stale cache, reassign=True → re-evaluate (only case that should)."""
        assigned_at = datetime(2026, 4, 10)
        last_updated_at = datetime(2026, 4, 15)
        assert self._should_use_cache(assigned_at, last_updated_at, reassign=True) is False

    def test_same_timestamp_uses_cache(self):
        """assigned_at == last_updated_at → cache is not stale, use it."""
        ts = datetime(2026, 4, 15)
        assert self._should_use_cache(ts, ts, reassign=False) is True
        assert self._should_use_cache(ts, ts, reassign=True) is True

    def test_flow_uses_break_not_continue(self):
        """The fixed code must use `break` to exit the inner personalisation loop,
        not `continue` which skips to the next personalisation and lets post-loop
        code overwrite the cached result.
        """
        source_file = "nova_manager/flows/get_user_experience_variant_flow_async.py"
        with open(source_file) as f:
            source = f.read()

        # Find the cache-hit block: the line that assigns existing_user_experience
        # followed by break (not continue)
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "experience_variant_assignment = existing_user_experience" in line:
                # Next non-empty line should be break
                for j in range(i + 1, min(i + 3, len(lines))):
                    stripped = lines[j].strip()
                    if stripped:
                        assert stripped == "break", \
                            f"Expected 'break' after cache assignment, got '{stripped}'"
                        return
        pytest.fail("Could not find 'experience_variant_assignment = existing_user_experience' in source")


# ────────────────────────────────────────────────────────────────────
# Bug 3: Timezone mismatch — track_event() used naive datetime
# ────────────────────────────────────────────────────────────────────


class TestTrackEventTimezone:
    """track_event() must use timezone-aware UTC datetimes, consistent
    with track_events() which uses datetime.now(timezone.utc).
    """

    def test_track_event_source_uses_timezone_utc(self):
        """Verify the source code of track_event uses datetime.now(timezone.utc)."""
        source_file = "nova_manager/components/metrics/events_controller.py"
        with open(source_file) as f:
            source = f.read()

        # Find the track_event method body (between def track_event and the next def)
        start = source.index("def track_event(")
        next_def = source.index("\n    def ", start + 1)
        method_source = source[start:next_def]

        assert "datetime.now(timezone.utc)" in method_source, \
            "track_event must use datetime.now(timezone.utc), not datetime.now()"
        # Ensure there's no bare datetime.now() (without timezone.utc)
        remaining = method_source.replace("datetime.now(timezone.utc)", "")
        assert "datetime.now()" not in remaining, \
            "track_event must not contain bare datetime.now() calls"


# ────────────────────────────────────────────────────────────────────
# Bug 4: Debug print leaking invite tokens
# ────────────────────────────────────────────────────────────────────


class TestNoDebugPrint:
    """Production code must not contain print() calls that leak sensitive data."""

    def test_auth_request_response_has_no_print(self):
        """The company validator must not print invite tokens to stdout."""
        from nova_manager.api.auth import request_response

        source = inspect.getsource(request_response)
        # There should be no print() calls in this module
        assert "print(" not in source, \
            "request_response.py contains a print() statement that leaks invite tokens"


# ────────────────────────────────────────────────────────────────────
# Bug 7: Variant split did not follow the configured percentages
# ────────────────────────────────────────────────────────────────────


class TestVariantSplitFollowsConfiguredPercentages:
    """Each variant used to get its own independent hash, and a user no variant
    claimed fell back to the first one. That is not a partition: a 50/50 test
    served 75/25 and a 90/10 test served 99/1.
    """

    EXPERIENCE_ID = uuid.UUID(int=1)
    PERSONALISATION_ID = uuid.UUID(int=2)
    # Fixed ids, so the sample — and therefore the result — is the same every run.
    USERS = [SimpleNamespace(pid=uuid.UUID(int=n)) for n in range(1000, 21000)]
    TOLERANCE = 2.0  # percentage points

    @staticmethod
    def _variants(*percentages):
        """Link rows in creation order: ids 1, 2, 3… named A, B, C…"""
        return [
            SimpleNamespace(
                id=position,
                target_percentage=percentage,
                experience_variant_id=uuid.UUID(int=100 + position),
                experience_variant=chr(64 + position),
            )
            for position, percentage in enumerate(percentages, start=1)
        ]

    FLOW = GetUserExperienceVariantFlowAsync(AsyncMock())

    def _pick(self, user, variants):
        return self.FLOW._select_experience_variant_by_target_percentage(
            user=user,
            experience_id=self.EXPERIENCE_ID,
            personalisation_id=self.PERSONALISATION_ID,
            experience_variants=variants,
        )

    def _served(self, variants, users=None):
        users = self.USERS if users is None else users
        counts = Counter(self._pick(user, variants) for user in users)
        return {
            link.experience_variant: 100 * counts[link.experience_variant] / len(users)
            for link in variants
        }

    @pytest.mark.parametrize(
        "percentages",
        [(50, 50), (90, 10), (10, 90), (34, 33, 33), (25, 25, 25, 25)],
    )
    def test_each_variant_is_served_its_configured_share(self, percentages):
        variants = self._variants(*percentages)

        served = self._served(variants)

        for link in variants:
            assert served[link.experience_variant] == pytest.approx(
                link.target_percentage, abs=self.TOLERANCE
            )

    def test_a_user_gets_the_same_variant_whatever_order_the_rows_load_in(self):
        # The relationship has no ORDER BY, so the list order is whatever the
        # database returns. The pick must not depend on it.
        variants = self._variants(34, 33, 33)
        users = self.USERS[:2000]

        in_order = [self._pick(user, variants) for user in users]
        reversed_order = [self._pick(user, variants[::-1]) for user in users]

        assert in_order == reversed_order

    def test_the_split_holds_among_users_let_in_by_a_partial_rollout(self):
        # Reusing the rollout gate's hash for the variant pick would send every
        # user of a 20% rollout to the first variant: they all hash below 0.2.
        rollout_context = f"{self.EXPERIENCE_ID}:{self.PERSONALISATION_ID}"
        let_in = [
            user
            for user in self.USERS
            if RuleEvaluator().evaluate_target_percentage(str(user.pid), 20, rollout_context)
        ]
        variants = self._variants(50, 50)

        served = self._served(variants, users=let_in)

        assert served["A"] == pytest.approx(50, abs=3.0)

    def test_percentages_short_of_100_leave_the_remainder_with_the_first_variant(self):
        # Update does not re-check that percentages sum to 100, so this state is
        # reachable. 30 + 30 leaves 40 unclaimed; it goes to the first variant.
        variants = self._variants(30, 30)

        served = self._served(variants)

        assert served["A"] == pytest.approx(70, abs=self.TOLERANCE)

    def test_a_zero_percent_variant_is_served_to_nobody(self):
        variants = self._variants(0, 100)

        served = self._served(variants, users=self.USERS[:2000])

        assert served["A"] == 0

    def test_a_single_variant_is_served_to_everyone(self):
        # Every CMS deployment today is one variant at 100%.
        variants = self._variants(100)

        served = self._served(variants, users=self.USERS[:2000])

        assert served["A"] == 100
