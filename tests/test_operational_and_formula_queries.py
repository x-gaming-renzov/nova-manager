"""Unit tests for operational and formula metric types in QueryBuilder.

These test SQL generation only — no ClickHouse connection needed.
"""

import pytest
import re

from nova_manager.components.metrics.query_builder import QueryBuilder


ORG_ID = "test_org"
APP_ID = "test_app"


def qb():
    return QueryBuilder(ORG_ID, APP_ID)


# ── Operational metric tests ─────────────────────────────────


class TestOperationalQuery:
    def test_basic_sum(self):
        sql = qb().build_query(
            "operational",
            {
                "metric_name": "marketing_spend",
                "aggregation": "sum",
                "time_range": {"start": "2026-01-01 00:00:00", "end": "2026-07-01 00:00:00"},
                "granularity": "monthly",
                "group_by": [],
                "filters": {},
            },
        )
        assert "business_metrics FINAL" in sql
        assert "SUM(value) AS value" in sql
        assert "metric_name = 'marketing_spend'" in sql
        assert "toStartOfMonth(period_start) AS period" in sql
        assert "GROUP BY period" in sql
        assert "ORDER BY period" in sql

    def test_avg_aggregation(self):
        sql = qb().build_query(
            "operational",
            {
                "metric_name": "cpi",
                "aggregation": "avg",
                "time_range": {"start": "2026-01-01 00:00:00", "end": "2026-07-01 00:00:00"},
                "granularity": "daily",
                "group_by": [],
                "filters": {},
            },
        )
        assert "AVG(value) AS value" in sql
        assert "toStartOfDay(period_start) AS period" in sql

    def test_dimension_filter(self):
        sql = qb().build_query(
            "operational",
            {
                "metric_name": "marketing_spend",
                "dimension_filter": "google_ads",
                "aggregation": "sum",
                "time_range": {"start": "2026-01-01 00:00:00", "end": "2026-07-01 00:00:00"},
                "granularity": "monthly",
                "group_by": [],
                "filters": {},
            },
        )
        assert "dimension = 'google_ads'" in sql

    def test_group_by_dimension(self):
        sql = qb().build_query(
            "operational",
            {
                "metric_name": "marketing_spend",
                "aggregation": "sum",
                "time_range": {"start": "2026-01-01 00:00:00", "end": "2026-07-01 00:00:00"},
                "granularity": "monthly",
                "group_by": [{"key": "dimension", "source": ""}],
                "filters": {},
            },
        )
        assert "dimension" in sql
        assert "GROUP BY period, dimension" in sql

    def test_uses_correct_table(self):
        sql = qb().build_query(
            "operational",
            {
                "metric_name": "sponsorship_revenue",
                "aggregation": "sum",
                "time_range": {"start": "2026-01-01 00:00:00", "end": "2026-07-01 00:00:00"},
                "granularity": "monthly",
                "group_by": [],
                "filters": {},
            },
        )
        assert "org_test_org_app_test_app.business_metrics" in sql
        # Should NOT reference raw_events
        assert "raw_events" not in sql

    def test_no_user_id_in_query(self):
        sql = qb().build_query(
            "operational",
            {
                "metric_name": "marketing_spend",
                "aggregation": "sum",
                "time_range": {"start": "2026-01-01 00:00:00", "end": "2026-07-01 00:00:00"},
                "granularity": "monthly",
                "group_by": [],
                "filters": {},
            },
        )
        assert "user_id" not in sql

    def test_relative_time_range(self):
        sql = qb().build_query(
            "operational",
            {
                "metric_name": "marketing_spend",
                "aggregation": "sum",
                "time_range": "6m",
                "granularity": "monthly",
                "group_by": [],
                "filters": {},
            },
        )
        assert "period_start >=" in sql
        assert "period_start <" in sql

    def test_weekly_granularity(self):
        sql = qb().build_query(
            "operational",
            {
                "metric_name": "marketing_spend",
                "aggregation": "sum",
                "time_range": {"start": "2026-01-01 00:00:00", "end": "2026-07-01 00:00:00"},
                "granularity": "weekly",
                "group_by": [],
                "filters": {},
            },
        )
        assert "toMonday(period_start) AS period" in sql

    def test_min_max_aggregations(self):
        for agg in ("min", "max"):
            sql = qb().build_query(
                "operational",
                {
                    "metric_name": "deal_value",
                    "aggregation": agg,
                    "time_range": {"start": "2026-01-01 00:00:00", "end": "2026-07-01 00:00:00"},
                    "granularity": "monthly",
                    "group_by": [],
                    "filters": {},
                },
            )
            assert f"{agg.upper()}(value) AS value" in sql


# ── Formula metric tests ─────────────────────────────────────


class TestFormulaQuery:
    def test_basic_division_two_operands(self):
        """CAC = spend / MAU"""
        sql = qb().build_query(
            "formula",
            {
                "time_range": {"start": "2026-01-01 00:00:00", "end": "2026-07-01 00:00:00"},
                "granularity": "monthly",
                "group_by": [],
                "operands": {
                    "spend": {
                        "type": "operational",
                        "config": {
                            "metric_name": "marketing_spend",
                            "aggregation": "sum",
                        },
                    },
                    "mau": {
                        "type": "count",
                        "config": {
                            "event_name": "session_start",
                            "distinct": True,
                        },
                    },
                },
                "expression": "spend / mau",
            },
        )
        # Should have CTEs
        assert "WITH" in sql
        assert "op_spend AS" in sql
        assert "op_mau AS" in sql
        # Division with nullIf
        assert "nullIf(op_mau.value, 0)" in sql
        # JOIN on period
        assert "op_spend.period = op_mau.period" in sql
        # Operational CTE uses business_metrics
        assert "business_metrics FINAL" in sql
        # Count CTE uses raw_events
        assert "raw_events" in sql

    def test_subtraction(self):
        """Net Margin = revenue - spend"""
        sql = qb().build_query(
            "formula",
            {
                "time_range": {"start": "2026-01-01 00:00:00", "end": "2026-07-01 00:00:00"},
                "granularity": "monthly",
                "group_by": [],
                "operands": {
                    "revenue": {
                        "type": "operational",
                        "config": {
                            "metric_name": "total_revenue",
                            "aggregation": "sum",
                        },
                    },
                    "spend": {
                        "type": "operational",
                        "config": {
                            "metric_name": "marketing_spend",
                            "aggregation": "sum",
                        },
                    },
                },
                "expression": "revenue - spend",
            },
        )
        assert "op_revenue.value - op_spend.value" in sql

    def test_multiplication(self):
        sql = qb().build_query(
            "formula",
            {
                "time_range": {"start": "2026-01-01 00:00:00", "end": "2026-07-01 00:00:00"},
                "granularity": "monthly",
                "group_by": [],
                "operands": {
                    "a": {
                        "type": "operational",
                        "config": {"metric_name": "x", "aggregation": "sum"},
                    },
                    "b": {
                        "type": "operational",
                        "config": {"metric_name": "y", "aggregation": "sum"},
                    },
                },
                "expression": "a * b",
            },
        )
        assert "op_a.value * op_b.value" in sql

    def test_complex_expression_with_parens(self):
        """ROAS with constant: (revenue - spend) / spend"""
        sql = qb().build_query(
            "formula",
            {
                "time_range": {"start": "2026-01-01 00:00:00", "end": "2026-07-01 00:00:00"},
                "granularity": "monthly",
                "group_by": [],
                "operands": {
                    "revenue": {
                        "type": "operational",
                        "config": {"metric_name": "total_revenue", "aggregation": "sum"},
                    },
                    "spend": {
                        "type": "operational",
                        "config": {"metric_name": "marketing_spend", "aggregation": "sum"},
                    },
                },
                "expression": "(revenue - spend) / spend",
            },
        )
        assert "( op_revenue.value - op_spend.value )" in sql
        assert "nullIf(op_spend.value, 0)" in sql

    def test_formula_overrides_time_range(self):
        """Formula's time_range should override operand configs."""
        sql = qb().build_query(
            "formula",
            {
                "time_range": {"start": "2026-06-01 00:00:00", "end": "2026-07-01 00:00:00"},
                "granularity": "monthly",
                "group_by": [],
                "operands": {
                    "spend": {
                        "type": "operational",
                        "config": {
                            "metric_name": "marketing_spend",
                            "aggregation": "sum",
                            "time_range": {"start": "2000-01-01", "end": "2000-12-31"},
                        },
                    },
                    "mau": {
                        "type": "count",
                        "config": {
                            "event_name": "login",
                            "distinct": True,
                            "time_range": {"start": "2000-01-01", "end": "2000-12-31"},
                        },
                    },
                },
                "expression": "spend / mau",
            },
        )
        # Formula time_range should be used, not the operand's
        assert "2026-06-01" in sql
        assert "2026-07-01" in sql
        # Operand's time_range should NOT appear
        assert "2000-01-01" not in sql

    def test_formula_with_aggregation_operand(self):
        """Revenue per tournament: revenue / avg_participants."""
        sql = qb().build_query(
            "formula",
            {
                "time_range": {"start": "2026-01-01 00:00:00", "end": "2026-07-01 00:00:00"},
                "granularity": "monthly",
                "group_by": [],
                "operands": {
                    "revenue": {
                        "type": "operational",
                        "config": {"metric_name": "total_revenue", "aggregation": "sum"},
                    },
                    "tournaments": {
                        "type": "count",
                        "config": {"event_name": "tournament.created", "distinct": False},
                    },
                },
                "expression": "revenue / tournaments",
            },
        )
        assert "op_revenue AS" in sql
        assert "op_tournaments AS" in sql
        assert "nullIf(op_tournaments.value, 0)" in sql

    def test_three_operands(self):
        """(revenue - spend) / mau"""
        sql = qb().build_query(
            "formula",
            {
                "time_range": {"start": "2026-01-01 00:00:00", "end": "2026-07-01 00:00:00"},
                "granularity": "monthly",
                "group_by": [],
                "operands": {
                    "revenue": {
                        "type": "operational",
                        "config": {"metric_name": "total_revenue", "aggregation": "sum"},
                    },
                    "spend": {
                        "type": "operational",
                        "config": {"metric_name": "marketing_spend", "aggregation": "sum"},
                    },
                    "mau": {
                        "type": "count",
                        "config": {"event_name": "session_start", "distinct": True},
                    },
                },
                "expression": "(revenue - spend) / mau",
            },
        )
        assert "op_revenue AS" in sql
        assert "op_spend AS" in sql
        assert "op_mau AS" in sql
        # Two JOINs
        assert sql.count("JOIN op_") == 2

    def test_numeric_literal_in_expression(self):
        """spend * 100 / mau"""
        sql = qb().build_query(
            "formula",
            {
                "time_range": {"start": "2026-01-01 00:00:00", "end": "2026-07-01 00:00:00"},
                "granularity": "monthly",
                "group_by": [],
                "operands": {
                    "spend": {
                        "type": "operational",
                        "config": {"metric_name": "marketing_spend", "aggregation": "sum"},
                    },
                    "mau": {
                        "type": "count",
                        "config": {"event_name": "session_start", "distinct": True},
                    },
                },
                "expression": "spend * 100 / mau",
            },
        )
        assert "100" in sql
        assert "op_spend.value * 100" in sql


# ── Expression parser safety tests ───────────────────────────


class TestExpressionParser:
    def test_rejects_sql_injection(self):
        with pytest.raises(ValueError, match="Invalid token"):
            QueryBuilder._safe_parse_expression(
                "; DROP TABLE users", ["spend", "mau"]
            )

    def test_rejects_unknown_operand(self):
        with pytest.raises(ValueError, match="Invalid token.*unknown_metric"):
            QueryBuilder._safe_parse_expression(
                "spend / unknown_metric", ["spend", "mau"]
            )

    def test_rejects_sql_keywords(self):
        with pytest.raises(ValueError):
            QueryBuilder._safe_parse_expression(
                "SELECT * FROM users", ["spend"]
            )

    def test_rejects_semicolons(self):
        with pytest.raises(ValueError):
            QueryBuilder._safe_parse_expression(
                "spend; DROP", ["spend"]
            )

    def test_rejects_comments(self):
        with pytest.raises(ValueError):
            QueryBuilder._safe_parse_expression(
                "spend -- comment", ["spend"]
            )

    def test_rejects_quotes(self):
        # Quotes won't be tokenized as valid tokens
        with pytest.raises(ValueError):
            QueryBuilder._safe_parse_expression(
                "spend / 'injection'", ["spend"]
            )

    def test_allows_valid_expression(self):
        result = QueryBuilder._safe_parse_expression(
            "a + b", ["a", "b"]
        )
        assert "op_a.value" in result
        assert "op_b.value" in result
        assert "+" in result

    def test_allows_parentheses(self):
        result = QueryBuilder._safe_parse_expression(
            "(a - b) / c", ["a", "b", "c"]
        )
        assert "(" in result
        assert ")" in result

    def test_allows_numeric_literals(self):
        result = QueryBuilder._safe_parse_expression(
            "a * 100", ["a"]
        )
        assert "100" in result

    def test_allows_float_literals(self):
        result = QueryBuilder._safe_parse_expression(
            "a * 1.5", ["a"]
        )
        assert "1.5" in result

    def test_division_wraps_nullif(self):
        result = QueryBuilder._safe_parse_expression(
            "a / b", ["a", "b"]
        )
        assert "nullIf(op_b.value, 0)" in result

    def test_no_formula_nesting(self):
        with pytest.raises(ValueError, match="cannot be of type 'formula'"):
            qb().build_query(
                "formula",
                {
                    "time_range": {"start": "2026-01-01", "end": "2026-07-01"},
                    "granularity": "monthly",
                    "group_by": [],
                    "operands": {
                        "inner": {
                            "type": "formula",
                            "config": {},
                        },
                    },
                    "expression": "inner",
                },
            )

    def test_empty_operands_rejected(self):
        with pytest.raises(ValueError, match="at least one operand"):
            qb().build_query(
                "formula",
                {
                    "time_range": {"start": "2026-01-01", "end": "2026-07-01"},
                    "granularity": "monthly",
                    "group_by": [],
                    "operands": {},
                    "expression": "",
                },
            )

    def test_unmatched_opening_paren(self):
        with pytest.raises(ValueError, match="Unmatched opening parenthesis"):
            QueryBuilder._safe_parse_expression("(a + b", ["a", "b"])

    def test_unmatched_closing_paren(self):
        with pytest.raises(ValueError, match="Unmatched closing parenthesis"):
            QueryBuilder._safe_parse_expression("a + b)", ["a", "b"])


# ── SQL injection safety tests for operational ────────────


class TestOperationalSQLSafety:
    def test_rejects_sql_injection_in_metric_name(self):
        with pytest.raises(ValueError, match="Unsafe characters"):
            qb().build_query(
                "operational",
                {
                    "metric_name": "test'; DROP TABLE x; --",
                    "aggregation": "sum",
                    "time_range": {"start": "2026-01-01", "end": "2026-07-01"},
                    "granularity": "monthly",
                    "group_by": [],
                    "filters": {},
                },
            )

    def test_rejects_sql_injection_in_dimension_filter(self):
        with pytest.raises(ValueError, match="Unsafe characters"):
            qb().build_query(
                "operational",
                {
                    "metric_name": "marketing_spend",
                    "dimension_filter": "x' OR '1'='1",
                    "aggregation": "sum",
                    "time_range": {"start": "2026-01-01", "end": "2026-07-01"},
                    "granularity": "monthly",
                    "group_by": [],
                    "filters": {},
                },
            )

    def test_rejects_invalid_aggregation(self):
        with pytest.raises(ValueError, match="Invalid aggregation"):
            qb().build_query(
                "operational",
                {
                    "metric_name": "marketing_spend",
                    "aggregation": "DROP",
                    "time_range": {"start": "2026-01-01", "end": "2026-07-01"},
                    "granularity": "monthly",
                    "group_by": [],
                    "filters": {},
                },
            )

    def test_allows_safe_metric_names(self):
        for name in ["marketing_spend", "to-incentive", "revenue.total", "Q1_2026"]:
            sql = qb().build_query(
                "operational",
                {
                    "metric_name": name,
                    "aggregation": "sum",
                    "time_range": {"start": "2026-01-01", "end": "2026-07-01"},
                    "granularity": "monthly",
                    "group_by": [],
                    "filters": {},
                },
            )
            assert f"metric_name = '{name}'" in sql
