"""Tests for retention query generation in QueryBuilder.

Verifies that the generated SQL uses only equality conditions in JOIN ON
clauses, which is required by ClickHouse (non-equality cross-table conditions
in JOIN ON cause error code 403 INVALID_JOIN_ON_EXPRESSION).
"""

import re

import pytest

from nova_manager.components.metrics.query_builder import QueryBuilder

ORG_ID = "test-org"
APP_ID = "test-app"


def _base_retention_config(**overrides):
    config = {
        "time_range": {
            "start": "2026-03-18 12:17:18",
            "end": "2026-04-17 12:17:18",
        },
        "granularity": "daily",
        "group_by": [],
        "filters": {},
        "initial_event": {
            "event_name": "auth.login_success",
            "distinct": False,
        },
        "return_event": {
            "event_name": "role.switched",
            "distinct": False,
        },
        "retention_window": "30d",
    }
    config.update(overrides)
    return config


def _extract_join_on_conditions(sql: str) -> list[str]:
    """Extract all JOIN ... ON condition blocks from the SQL."""
    # Match "JOIN <table> ON <conditions>" up to the next keyword or newline block
    pattern = r"JOIN\s+\S+\s+\S+\s+ON\s+(.+?)(?=\n\s*(?:WHERE|GROUP|ORDER|LEFT|INNER|RIGHT|FULL|$))"
    return re.findall(pattern, sql, re.DOTALL)


class TestRetentionQuery:
    def test_basic_retention_generates_valid_sql(self):
        qb = QueryBuilder(ORG_ID, APP_ID)
        sql = qb.build_query("retention", _base_retention_config())

        assert "initial_cohort" in sql
        assert "return_events" in sql
        assert "filtered_returns" in sql

    def test_no_cross_table_inequality_in_join_on(self):
        """The ClickHouse bug: JOIN ON must not have cross-table > or < conditions."""
        qb = QueryBuilder(ORG_ID, APP_ID)
        sql = qb.build_query("retention", _base_retention_config())

        join_conditions = _extract_join_on_conditions(sql)
        for cond in join_conditions:
            # Each individual condition should be equality only (no > or <)
            # Split by AND to check each sub-condition
            parts = [p.strip() for p in cond.split("AND")]
            for part in parts:
                assert ">" not in part and "<" not in part, (
                    f"JOIN ON contains non-equality condition: {part}"
                )

    def test_time_window_in_where_clause(self):
        """The time-window filter should be in the filtered_returns WHERE, not JOIN ON."""
        qb = QueryBuilder(ORG_ID, APP_ID)
        sql = qb.build_query("retention", _base_retention_config())

        # The filtered_returns CTE should contain the time-window WHERE
        assert "WHERE r.ret_ts > i.first_ts" in sql
        assert "INTERVAL 30 DAY" in sql

    def test_left_join_to_filtered_returns(self):
        """Final query should LEFT JOIN to filtered_returns, not directly to return_events."""
        qb = QueryBuilder(ORG_ID, APP_ID)
        sql = qb.build_query("retention", _base_retention_config())

        assert "LEFT JOIN filtered_returns fr" in sql
        # Should NOT have a direct LEFT JOIN to return_events
        assert "LEFT JOIN return_events" not in sql

    def test_retention_with_group_by(self):
        """Group-by keys should be carried through filtered_returns and used in JOIN ON."""
        qb = QueryBuilder(ORG_ID, APP_ID)
        config = _base_retention_config(
            group_by=[{"key": "country", "source": "user_profile"}]
        )
        sql = qb.build_query("retention", config)

        # filtered_returns CTE should select the group_by column
        assert "i.country" in sql
        # Final JOIN should include group_by equality
        assert "fr.country = i.country" in sql

    def test_retention_window_variants(self):
        """Different retention windows should produce correct INTERVAL SQL."""
        qb = QueryBuilder(ORG_ID, APP_ID)

        for window, expected in [
            ("7d", "INTERVAL 7 DAY"),
            ("24h", "INTERVAL 24 HOUR"),
            ("1w", "INTERVAL 1 WEEK"),
            ("3m", "INTERVAL 3 MONTH"),
        ]:
            config = _base_retention_config(retention_window=window)
            sql = qb.build_query("retention", config)
            assert expected in sql, f"Window '{window}' should produce '{expected}'"

    def test_retention_cohort_and_retained_columns(self):
        """Output should include cohort_users, retained_users, and value."""
        qb = QueryBuilder(ORG_ID, APP_ID)
        sql = qb.build_query("retention", _base_retention_config())

        assert "cohort_users" in sql
        assert "retained_users" in sql
        assert "AS value" in sql

    def test_retention_with_filters(self):
        """Filters should be applied within the initial and return event CTEs."""
        qb = QueryBuilder(ORG_ID, APP_ID)
        config = _base_retention_config(
            filters={"user_id": {"value": "user123", "source": "event_properties", "op": "="}}
        )
        sql = qb.build_query("retention", config)

        # Both CTEs should have the filter applied
        assert "user123" in sql

    def test_retention_with_multiple_group_by(self):
        """Multiple group-by keys should all be carried through."""
        qb = QueryBuilder(ORG_ID, APP_ID)
        config = _base_retention_config(
            group_by=[
                {"key": "country", "source": "user_profile"},
                {"key": "platform", "source": "event_properties"},
            ]
        )
        sql = qb.build_query("retention", config)

        assert "fr.country = i.country" in sql
        assert "fr.platform = i.platform" in sql
