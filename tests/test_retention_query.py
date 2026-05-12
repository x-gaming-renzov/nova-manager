"""Tests for retention query generation in QueryBuilder.

Verifies that the generated SQL:
- Uses only equality conditions in JOIN ON clauses (ClickHouse requirement)
- Places time-window filtering inside aggregation functions
- Handles group_by, filters, and window variants correctly
"""

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


class TestRetentionQuery:
    def test_basic_retention_generates_valid_sql(self):
        qb = QueryBuilder(ORG_ID, APP_ID)
        sql = qb.build_query("retention", _base_retention_config())

        assert "initial_cohort" in sql
        assert "return_events" in sql

    def test_no_cross_table_inequality_in_join_on(self):
        """JOIN ON must not have cross-table > or < conditions (ClickHouse error 403)."""
        qb = QueryBuilder(ORG_ID, APP_ID)
        sql = qb.build_query("retention", _base_retention_config())

        # Find all JOIN ... ON blocks
        import re
        on_blocks = re.findall(
            r"ON\s+(.+?)(?=\n\s*(?:WHERE|GROUP|ORDER|$))", sql, re.DOTALL
        )
        for block in on_blocks:
            parts = [p.strip() for p in block.split("AND")]
            for part in parts:
                assert ">" not in part and "<" not in part, (
                    f"JOIN ON contains non-equality condition: {part}"
                )

    def test_time_window_in_aggregation(self):
        """Time-window check should be inside uniqExactIf, not in JOIN ON or CTE WHERE."""
        qb = QueryBuilder(ORG_ID, APP_ID)
        sql = qb.build_query("retention", _base_retention_config())

        assert "uniqExactIf(i.user_id, r.ret_ts > i.first_ts" in sql
        assert "INTERVAL 30 DAY" in sql

    def test_left_join_on_user_id_only(self):
        """Final query should LEFT JOIN return_events on user_id equality only."""
        qb = QueryBuilder(ORG_ID, APP_ID)
        sql = qb.build_query("retention", _base_retention_config())

        assert "LEFT JOIN return_events r" in sql
        assert "ON r.user_id = i.user_id" in sql

    def test_no_filtered_returns_cte(self):
        """Should NOT use a filtered_returns CTE (ClickHouse ignores WHERE in CTE JOINs)."""
        qb = QueryBuilder(ORG_ID, APP_ID)
        sql = qb.build_query("retention", _base_retention_config())

        assert "filtered_returns" not in sql

    def test_retention_with_group_by(self):
        """Group-by keys should appear in SELECT, GROUP BY."""
        qb = QueryBuilder(ORG_ID, APP_ID)
        config = _base_retention_config(
            group_by=[{"key": "country", "source": "user_profile"}]
        )
        sql = qb.build_query("retention", config)

        assert "i.country" in sql

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

        assert "user123" in sql

    def test_retained_condition_matches_window(self):
        """The retained condition should use the exact window from config."""
        qb = QueryBuilder(ORG_ID, APP_ID)
        config = _base_retention_config(retention_window="1h")
        sql = qb.build_query("retention", config)

        assert "r.ret_ts > i.first_ts AND r.ret_ts < i.first_ts + INTERVAL 1 HOUR" in sql
