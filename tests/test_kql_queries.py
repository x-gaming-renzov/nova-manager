"""Unit tests for KQL query generation in KQLQueryBuilder.

Mirrors test_compute_queries.py and test_operational_and_formula_queries.py
but asserts KQL-specific patterns instead of ClickHouse SQL.
"""

import re
import pytest

from nova_manager.components.metrics.kql_query_builder import KQLQueryBuilder

ORG_ID = "test-org"
APP_ID = "test-app"
TR = {"start": "2026-03-18 12:17:18", "end": "2026-04-17 12:17:18"}


def _qb():
    return KQLQueryBuilder(ORG_ID, APP_ID)


# ── Count queries ───────────────────────────────────────────


class TestKQLCountQuery:
    def test_basic_count(self):
        kql = _qb().build_query("count", {
            "event_name": "auth.login_success", "distinct": False,
            "time_range": TR, "granularity": "daily", "group_by": [], "filters": {},
        })
        assert "count()" in kql
        assert "auth.login_success" in kql
        assert "raw_events" in kql

    def test_distinct_count(self):
        kql = _qb().build_query("count", {
            "event_name": "auth.login_success", "distinct": True,
            "time_range": TR, "granularity": "daily", "group_by": [], "filters": {},
        })
        assert "dcount(user_id)" in kql

    @pytest.mark.parametrize("granularity,expected", [
        ("hourly", "bin(client_ts, 1h)"),
        ("daily", "bin(client_ts, 1d)"),
        ("weekly", "startofweek(client_ts)"),
        ("monthly", "startofmonth(client_ts)"),
    ])
    def test_granularities(self, granularity, expected):
        kql = _qb().build_query("count", {
            "event_name": "auth.login_success", "distinct": False,
            "time_range": TR, "granularity": granularity, "group_by": [], "filters": {},
        })
        assert expected in kql

    def test_group_by_event_property(self):
        kql = _qb().build_query("count", {
            "event_name": "screen.viewed", "distinct": False,
            "time_range": TR, "granularity": "daily",
            "group_by": [{"key": "page", "source": "event_properties"}],
            "filters": {},
        })
        assert "page" in kql
        assert "summarize" in kql
        assert "event_props" in kql

    @pytest.mark.parametrize("op,kql_op", [("=", "=="), ("!=", "!="), (">", ">"), ("<", "<"), (">=", ">="), ("<=", "<=")])
    def test_filter_ops(self, op, kql_op):
        kql = _qb().build_query("count", {
            "event_name": "screen.viewed", "distinct": False,
            "time_range": TR, "granularity": "daily", "group_by": [],
            "filters": {"screen_name": {"source": "event_properties", "op": op, "value": "Home"}},
        })
        assert f"{kql_op} 'Home'" in kql

    def test_uses_datetime_literals(self):
        kql = _qb().build_query("count", {
            "event_name": "test", "distinct": False,
            "time_range": TR, "granularity": "daily", "group_by": [], "filters": {},
        })
        assert "datetime(2026-03-18 12:17:18)" in kql
        assert "datetime(2026-04-17 12:17:18)" in kql

    def test_pipe_syntax(self):
        kql = _qb().build_query("count", {
            "event_name": "test", "distinct": False,
            "time_range": TR, "granularity": "daily", "group_by": [], "filters": {},
        })
        assert "| where" in kql
        assert "| summarize" in kql
        assert "| order by" in kql

    def test_uses_correct_table(self):
        kql = _qb().build_query("count", {
            "event_name": "test", "distinct": False,
            "time_range": TR, "granularity": "daily", "group_by": [], "filters": {},
        })
        assert "raw_events" in kql
        # Per-org/app DB mode: no tenant columns in query
        assert "organisation_id" not in kql


# ── Aggregation queries ─────────────────────────────────────


class TestKQLAggregationQuery:
    @pytest.mark.parametrize("agg", ["sum", "avg", "min", "max"])
    def test_aggregation_types(self, agg):
        kql = _qb().build_query("aggregation", {
            "event_name": "purchase",
            "property": "amount", "aggregation": agg,
            "time_range": TR, "granularity": "daily", "group_by": [], "filters": {},
        })
        assert f"{agg}(todouble(" in kql

    def test_joins_event_props(self):
        kql = _qb().build_query("aggregation", {
            "event_name": "purchase", "property": "amount", "aggregation": "sum",
            "time_range": TR, "granularity": "daily", "group_by": [], "filters": {},
        })
        assert "event_props" in kql
        assert "amount" in kql


# ── Ratio queries ────────────────────────────────────────────


class TestKQLRatioQuery:
    def test_basic_ratio(self):
        kql = _qb().build_query("ratio", {
            "numerator": {"event_name": "tournament.created"},
            "denominator": {"event_name": "tournament.creation_started"},
            "time_range": TR, "granularity": "daily", "group_by": [], "filters": {},
        })
        assert "let num" in kql
        assert "let den" in kql
        assert "iff(" in kql  # safe division

    def test_ratio_uses_join(self):
        kql = _qb().build_query("ratio", {
            "numerator": {"event_name": "purchase"},
            "denominator": {"event_name": "page_view"},
            "time_range": TR, "granularity": "daily", "group_by": [], "filters": {},
        })
        assert "join" in kql
        assert "on period" in kql

    def test_ratio_distinct(self):
        kql = _qb().build_query("ratio", {
            "numerator": {"event_name": "purchase", "distinct": True},
            "denominator": {"event_name": "page_view", "distinct": True},
            "time_range": TR, "granularity": "daily", "group_by": [], "filters": {},
        })
        assert "dcount(user_id)" in kql


# ── Retention queries ────────────────────────────────────────


class TestKQLRetentionQuery:
    def test_basic_structure(self):
        kql = _qb().build_query("retention", {
            "time_range": TR, "granularity": "daily", "group_by": [], "filters": {},
            "initial_event": {"event_name": "auth.login_success"},
            "return_event": {"event_name": "role.switched"},
            "retention_window": "30d",
        })
        assert "let initial_cohort" in kql
        assert "let return_events" in kql
        assert "cohort_users" in kql
        assert "retained_users" in kql

    def test_uses_dcountif(self):
        kql = _qb().build_query("retention", {
            "time_range": TR, "granularity": "daily", "group_by": [], "filters": {},
            "initial_event": {"event_name": "auth.login_success"},
            "return_event": {"event_name": "role.switched"},
            "retention_window": "7d",
        })
        assert "dcountif(user_id, ret_ts > first_ts and ret_ts < first_ts + 7d)" in kql

    def test_retention_window_variants(self):
        for window, expected_ts in [
            ("7d", "7d"),
            ("24h", "24h"),
            ("1w", "7d"),  # weeks converted to days
            ("3m", "90d"),  # months converted to days
        ]:
            kql = _qb().build_query("retention", {
                "time_range": TR, "granularity": "daily", "group_by": [], "filters": {},
                "initial_event": {"event_name": "auth.login_success"},
                "return_event": {"event_name": "role.switched"},
                "retention_window": window,
            })
            assert f"first_ts + {expected_ts}" in kql, f"Window '{window}' should produce '{expected_ts}'"

    def test_output_columns(self):
        kql = _qb().build_query("retention", {
            "time_range": TR, "granularity": "daily", "group_by": [], "filters": {},
            "initial_event": {"event_name": "auth.login_success"},
            "return_event": {"event_name": "role.switched"},
            "retention_window": "30d",
        })
        assert "cohort_users" in kql
        assert "retained_users" in kql
        assert "value" in kql
        assert "period" in kql

    def test_left_join_on_user_id(self):
        kql = _qb().build_query("retention", {
            "time_range": TR, "granularity": "daily", "group_by": [], "filters": {},
            "initial_event": {"event_name": "auth.login_success"},
            "return_event": {"event_name": "role.switched"},
            "retention_window": "30d",
        })
        assert "join kind=leftouter" in kql
        assert "on user_id" in kql


# ── Operational queries ──────────────────────────────────────


class TestKQLOperationalQuery:
    def test_basic_sum(self):
        kql = _qb().build_query("operational", {
            "metric_name": "marketing_spend", "aggregation": "sum",
            "time_range": {"start": "2026-01-01 00:00:00", "end": "2026-07-01 00:00:00"},
            "granularity": "monthly", "group_by": [], "filters": {},
        })
        assert "business_metrics" in kql
        assert "sum(value)" in kql
        assert "metric_name == 'marketing_spend'" in kql
        assert "startofmonth(period_start)" in kql

    def test_dedup_via_arg_max(self):
        """ADX uses arg_max for ReplacingMergeTree equivalent dedup."""
        kql = _qb().build_query("operational", {
            "metric_name": "marketing_spend", "aggregation": "sum",
            "time_range": {"start": "2026-01-01 00:00:00", "end": "2026-07-01 00:00:00"},
            "granularity": "monthly", "group_by": [], "filters": {},
        })
        assert "arg_max(created_at, value)" in kql

    def test_dimension_filter(self):
        kql = _qb().build_query("operational", {
            "metric_name": "marketing_spend", "dimension_filter": "google_ads",
            "aggregation": "sum",
            "time_range": {"start": "2026-01-01 00:00:00", "end": "2026-07-01 00:00:00"},
            "granularity": "monthly", "group_by": [], "filters": {},
        })
        assert "dimension == 'google_ads'" in kql

    def test_scenario_id_filter(self):
        kql = _qb().build_query("operational", {
            "metric_name": "marketing_spend", "aggregation": "sum",
            "scenario_id": "scenario_v2",
            "time_range": {"start": "2026-01-01 00:00:00", "end": "2026-07-01 00:00:00"},
            "granularity": "monthly", "group_by": [], "filters": {},
        })
        assert "scenario_id == 'scenario_v2'" in kql

    def test_no_scenario_id_omits_where_filter(self):
        kql = _qb().build_query("operational", {
            "metric_name": "marketing_spend", "aggregation": "sum",
            "time_range": {"start": "2026-01-01 00:00:00", "end": "2026-07-01 00:00:00"},
            "granularity": "monthly", "group_by": [], "filters": {},
        })
        # scenario_id appears in dedup (arg_max by) but NOT as a where filter
        assert "scenario_id ==" not in kql

    def test_uses_correct_table(self):
        kql = _qb().build_query("operational", {
            "metric_name": "x", "aggregation": "sum",
            "time_range": {"start": "2026-01-01 00:00:00", "end": "2026-07-01 00:00:00"},
            "granularity": "monthly", "group_by": [], "filters": {},
        })
        assert "business_metrics" in kql
        assert "raw_events" not in kql

    def test_group_by_dimension(self):
        kql = _qb().build_query("operational", {
            "metric_name": "marketing_spend", "aggregation": "sum",
            "time_range": {"start": "2026-01-01 00:00:00", "end": "2026-07-01 00:00:00"},
            "granularity": "monthly",
            "group_by": [{"key": "dimension", "source": ""}],
            "filters": {},
        })
        assert "dimension" in kql

    def test_rejects_invalid_aggregation(self):
        with pytest.raises(ValueError, match="Invalid aggregation"):
            _qb().build_query("operational", {
                "metric_name": "x", "aggregation": "DROP",
                "time_range": {"start": "2026-01-01", "end": "2026-07-01"},
                "granularity": "monthly", "group_by": [], "filters": {},
            })

    def test_rejects_sql_injection_in_metric_name(self):
        with pytest.raises(ValueError, match="Unsafe characters"):
            _qb().build_query("operational", {
                "metric_name": "test'; DROP TABLE x; --", "aggregation": "sum",
                "time_range": {"start": "2026-01-01", "end": "2026-07-01"},
                "granularity": "monthly", "group_by": [], "filters": {},
            })


# ── Formula queries ──────────────────────────────────────────


class TestKQLFormulaQuery:
    def test_basic_division(self):
        kql = _qb().build_query("formula", {
            "time_range": {"start": "2026-01-01 00:00:00", "end": "2026-07-01 00:00:00"},
            "granularity": "monthly", "group_by": [],
            "operands": {
                "spend": {"type": "operational", "config": {"metric_name": "marketing_spend", "aggregation": "sum"}},
                "mau": {"type": "count", "config": {"event_name": "session_start", "distinct": True}},
            },
            "expression": "spend / mau",
        })
        assert "let op_spend" in kql
        assert "let op_mau" in kql
        # After join: first operand's value = "value", second = "value1"
        # Safe division wraps the denominator with todouble for type safety
        assert "iff(todouble(value1) == 0, real(null), todouble(value1))" in kql

    def test_subtraction(self):
        kql = _qb().build_query("formula", {
            "time_range": {"start": "2026-01-01 00:00:00", "end": "2026-07-01 00:00:00"},
            "granularity": "monthly", "group_by": [],
            "operands": {
                "revenue": {"type": "operational", "config": {"metric_name": "total_revenue", "aggregation": "sum"}},
                "spend": {"type": "operational", "config": {"metric_name": "marketing_spend", "aggregation": "sum"}},
            },
            "expression": "revenue - spend",
        })
        assert "value - value1" in kql

    def test_no_formula_nesting(self):
        with pytest.raises(ValueError, match="cannot be of type 'formula'"):
            _qb().build_query("formula", {
                "time_range": {"start": "2026-01-01", "end": "2026-07-01"},
                "granularity": "monthly", "group_by": [],
                "operands": {"inner": {"type": "formula", "config": {}}},
                "expression": "inner",
            })

    def test_empty_operands_rejected(self):
        with pytest.raises(ValueError, match="at least one operand"):
            _qb().build_query("formula", {
                "time_range": {"start": "2026-01-01", "end": "2026-07-01"},
                "granularity": "monthly", "group_by": [],
                "operands": {}, "expression": "",
            })

    def test_scenario_id_in_formula_operand(self):
        kql = _qb().build_query("formula", {
            "time_range": {"start": "2026-01-01 00:00:00", "end": "2026-07-01 00:00:00"},
            "granularity": "monthly", "group_by": [],
            "operands": {
                "spend": {"type": "operational", "config": {"metric_name": "marketing_spend", "aggregation": "sum", "scenario_id": "scenario_neutral"}},
                "mau": {"type": "operational", "config": {"metric_name": "mau", "aggregation": "sum", "scenario_id": "scenario_neutral"}},
            },
            "expression": "spend / mau",
        })
        assert kql.count("scenario_id == 'scenario_neutral'") == 2

    def test_three_operands(self):
        kql = _qb().build_query("formula", {
            "time_range": {"start": "2026-01-01 00:00:00", "end": "2026-07-01 00:00:00"},
            "granularity": "monthly", "group_by": [],
            "operands": {
                "revenue": {"type": "operational", "config": {"metric_name": "total_revenue", "aggregation": "sum"}},
                "spend": {"type": "operational", "config": {"metric_name": "marketing_spend", "aggregation": "sum"}},
                "mau": {"type": "count", "config": {"event_name": "session_start", "distinct": True}},
            },
            "expression": "(revenue - spend) / mau",
        })
        assert "let op_revenue" in kql
        assert "let op_spend" in kql
        assert "let op_mau" in kql


# ── Expression parser safety (reuses same parser logic) ──────


class TestKQLExpressionParser:
    def test_rejects_sql_injection(self):
        with pytest.raises(ValueError, match="Invalid token"):
            KQLQueryBuilder._safe_parse_expression("; DROP TABLE users", ["spend", "mau"])

    def test_rejects_unknown_operand(self):
        with pytest.raises(ValueError, match="Invalid token.*unknown_metric"):
            KQLQueryBuilder._safe_parse_expression("spend / unknown_metric", ["spend", "mau"])

    def test_division_wraps_iff(self):
        result = KQLQueryBuilder._safe_parse_expression("a / b", ["a", "b"])
        assert "iff(todouble(op_b.value) == 0, real(null), todouble(op_b.value))" in result

    def test_allows_valid_expression(self):
        result = KQLQueryBuilder._safe_parse_expression("a + b", ["a", "b"])
        assert "op_a.value" in result
        assert "op_b.value" in result

    def test_unused_operands_rejected(self):
        with pytest.raises(ValueError, match="Unused operand.*unused"):
            KQLQueryBuilder._safe_parse_expression("a + b", ["a", "b", "unused"])
