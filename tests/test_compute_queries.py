"""Tests for all metric compute query types documented in nova-compute-errors-2026-04-29.

Covers every frontend-verified scenario from the issue doc:
- count: basic, distinct, all granularities, group_by, filter ops
- aggregation: sum, avg, min, max
- ratio: basic
- retention: all window sizes, granularities, same-event, custom windows
"""

import re

import pytest

from nova_manager.components.metrics.query_builder import QueryBuilder

ORG_ID = "test-org"
APP_ID = "test-app"
TR = {"start": "2026-03-18 12:17:18", "end": "2026-04-17 12:17:18"}


def _qb():
    return QueryBuilder(ORG_ID, APP_ID)


def _assert_no_join_inequality(sql: str):
    """Assert no JOIN ON clause has cross-table > or < conditions."""
    on_blocks = re.findall(r"ON\s+(.+?)(?=\n\s*(?:WHERE|GROUP|ORDER|$))", sql, re.DOTALL)
    for block in on_blocks:
        for part in block.split("AND"):
            part = part.strip()
            assert ">" not in part and "<" not in part, (
                f"JOIN ON contains non-equality condition: {part}"
            )


# ── Count queries ───────────────────────────────────────────

class TestCountQuery:
    def test_basic_count(self):
        sql = _qb().build_query("count", {
            "event_name": "auth.login_success", "distinct": False,
            "time_range": TR, "granularity": "daily", "group_by": [], "filters": {},
        })
        assert "COUNT(*) AS value" in sql
        assert "auth.login_success" in sql

    def test_distinct_count(self):
        sql = _qb().build_query("count", {
            "event_name": "auth.login_success", "distinct": True,
            "time_range": TR, "granularity": "daily", "group_by": [], "filters": {},
        })
        assert "uniqExact(e.user_id) AS value" in sql

    @pytest.mark.parametrize("granularity,trunc_fn", [
        ("hourly", "toStartOfHour"),
        ("daily", "toStartOfDay"),
        ("weekly", "toMonday"),
        ("monthly", "toStartOfMonth"),
    ])
    def test_granularities(self, granularity, trunc_fn):
        sql = _qb().build_query("count", {
            "event_name": "auth.login_success", "distinct": False,
            "time_range": TR, "granularity": granularity, "group_by": [], "filters": {},
        })
        assert trunc_fn in sql

    def test_group_by_event_property(self):
        sql = _qb().build_query("count", {
            "event_name": "screen.viewed", "distinct": False,
            "time_range": TR, "granularity": "daily",
            "group_by": [{"key": "page", "source": "event_properties"}],
            "filters": {},
        })
        assert "ep_page.value AS page" in sql
        assert "GROUP BY" in sql

    @pytest.mark.parametrize("op", ["=", "!=", ">", "<", ">=", "<="])
    def test_filter_ops(self, op):
        sql = _qb().build_query("count", {
            "event_name": "screen.viewed", "distinct": False,
            "time_range": TR, "granularity": "daily", "group_by": [],
            "filters": {"screen_name": {"source": "event_properties", "op": op, "value": "Home"}},
        })
        assert f"{op} 'Home'" in sql

    def test_filter_like(self):
        sql = _qb().build_query("count", {
            "event_name": "screen.viewed", "distinct": False,
            "time_range": TR, "granularity": "daily", "group_by": [],
            "filters": {"screen_name": {"source": "event_properties", "op": "LIKE", "value": "%Home%"}},
        })
        assert "LIKE '%Home%'" in sql


# ── Aggregation queries ─────────────────────────────────────

class TestAggregationQuery:
    @pytest.mark.parametrize("agg", ["sum", "avg", "min", "max"])
    def test_aggregation_types(self, agg):
        sql = _qb().build_query("aggregation", {
            "event_name": "tournament.creation_step_completed",
            "property": "step_number", "aggregation": agg,
            "time_range": TR, "granularity": "daily", "group_by": [], "filters": {},
        })
        assert f"{agg.upper()}(toFloat64(p_val.value)) AS value" in sql

    def test_aggregation_joins_property(self):
        sql = _qb().build_query("aggregation", {
            "event_name": "purchase", "property": "amount", "aggregation": "sum",
            "time_range": TR, "granularity": "daily", "group_by": [], "filters": {},
        })
        assert "p_val" in sql
        assert "amount" in sql


# ── Ratio queries ────────────────────────────────────────────

class TestRatioQuery:
    def test_basic_ratio(self):
        sql = _qb().build_query("ratio", {
            "numerator": {"event_name": "tournament.created"},
            "denominator": {"event_name": "tournament.creation_started"},
            "time_range": TR, "granularity": "daily", "group_by": [], "filters": {},
        })
        assert "num" in sql
        assert "den" in sql
        assert "nullIf(den.value, 0)" in sql

    def test_ratio_with_group_by(self):
        sql = _qb().build_query("ratio", {
            "numerator": {"event_name": "purchase"},
            "denominator": {"event_name": "page_view"},
            "time_range": TR, "granularity": "daily",
            "group_by": [{"key": "country", "source": "event_properties"}],
            "filters": {},
        })
        assert "country" in sql


# ── Retention queries (the bug from the issue) ──────────────

class TestRetentionQuery:
    def test_no_join_inequality(self):
        """ClickHouse rejects non-equality cross-table JOIN ON conditions."""
        sql = _qb().build_query("retention", {
            "time_range": TR, "granularity": "daily", "group_by": [], "filters": {},
            "initial_event": {"event_name": "auth.login_success", "distinct": False},
            "return_event": {"event_name": "auth.login_success", "distinct": False},
            "retention_window": "1d",
        })
        _assert_no_join_inequality(sql)

    def test_no_filtered_returns_cte(self):
        """CTE WHERE after JOIN is silently ignored by ClickHouse."""
        sql = _qb().build_query("retention", {
            "time_range": TR, "granularity": "daily", "group_by": [], "filters": {},
            "initial_event": {"event_name": "auth.login_success", "distinct": False},
            "return_event": {"event_name": "role.switched", "distinct": False},
            "retention_window": "30d",
        })
        assert "filtered_returns" not in sql

    def test_window_in_aggregation(self):
        """Time-window check must be inside uniqExactIf, not in JOIN/WHERE."""
        sql = _qb().build_query("retention", {
            "time_range": TR, "granularity": "daily", "group_by": [], "filters": {},
            "initial_event": {"event_name": "auth.login_success", "distinct": False},
            "return_event": {"event_name": "role.switched", "distinct": False},
            "retention_window": "7d",
        })
        assert "uniqExactIf(i.user_id, r.ret_ts > i.first_ts AND r.ret_ts < i.first_ts + INTERVAL 7 DAY)" in sql

    # Reproducers from the issue doc
    def test_reproducer_login_to_login_1d(self):
        sql = _qb().build_query("retention", {
            "time_range": TR, "granularity": "daily", "group_by": [], "filters": {},
            "initial_event": {"event_name": "auth.login_success"},
            "return_event": {"event_name": "auth.login_success"},
            "retention_window": "1d",
        })
        _assert_no_join_inequality(sql)
        assert "INTERVAL 1 DAY" in sql

    def test_reproducer_login_to_tournament_7d(self):
        sql = _qb().build_query("retention", {
            "time_range": TR, "granularity": "daily", "group_by": [], "filters": {},
            "initial_event": {"event_name": "auth.login_success"},
            "return_event": {"event_name": "tournament.viewed"},
            "retention_window": "7d",
        })
        _assert_no_join_inequality(sql)

    def test_reproducer_signup_to_created_14d_weekly(self):
        sql = _qb().build_query("retention", {
            "time_range": TR, "granularity": "weekly", "group_by": [], "filters": {},
            "initial_event": {"event_name": "organizer.signup_started"},
            "return_event": {"event_name": "tournament.created"},
            "retention_window": "14d",
        })
        _assert_no_join_inequality(sql)
        assert "toMonday" in sql

    # Custom windows from the issue
    @pytest.mark.parametrize("window,expected_interval", [
        ("3d", "INTERVAL 3 DAY"),
        ("60d", "INTERVAL 60 DAY"),
        ("12h", "INTERVAL 12 HOUR"),
        ("2w", "INTERVAL 2 WEEK"),
        ("1d", "INTERVAL 1 DAY"),
        ("24h", "INTERVAL 24 HOUR"),
    ])
    def test_custom_windows(self, window, expected_interval):
        sql = _qb().build_query("retention", {
            "time_range": TR, "granularity": "daily", "group_by": [], "filters": {},
            "initial_event": {"event_name": "auth.login_success"},
            "return_event": {"event_name": "role.switched"},
            "retention_window": window,
        })
        assert expected_interval in sql
        _assert_no_join_inequality(sql)

    @pytest.mark.parametrize("granularity", ["hourly", "daily", "weekly", "monthly"])
    def test_all_granularities(self, granularity):
        sql = _qb().build_query("retention", {
            "time_range": TR, "granularity": granularity, "group_by": [], "filters": {},
            "initial_event": {"event_name": "auth.login_success"},
            "return_event": {"event_name": "role.switched"},
            "retention_window": "30d",
        })
        assert "cohort_users" in sql
        assert "retained_users" in sql
        _assert_no_join_inequality(sql)

    def test_output_columns(self):
        sql = _qb().build_query("retention", {
            "time_range": TR, "granularity": "daily", "group_by": [], "filters": {},
            "initial_event": {"event_name": "auth.login_success"},
            "return_event": {"event_name": "role.switched"},
            "retention_window": "30d",
        })
        assert "AS period" in sql
        assert "AS cohort_users" in sql
        assert "AS retained_users" in sql
        assert "AS value" in sql
