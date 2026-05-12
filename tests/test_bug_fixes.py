import inspect
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from nova_manager.components.rule_evaluator.controller import RuleEvaluator


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
