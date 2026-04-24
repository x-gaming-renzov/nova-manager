import pytest

from nova_manager.components.metrics.query_builder import QueryBuilder


@pytest.fixture
def query_builder():
    return QueryBuilder("test_org", "test_app")


@pytest.fixture
def retention_config():
    return {
        "type": "retention",
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


class TestRetentionQueryNoNonEquiJoin:
    """The retention query must use only equi-join conditions in LEFT JOIN ON.

    ClickHouse v24.8 rejects non-equi conditions (>, <) in JOIN ON clauses
    with INVALID_JOIN_ON_EXPRESSION. The time-window filtering must happen
    in the aggregation expression instead.
    """

    def test_join_on_has_only_equi_condition(self, query_builder, retention_config):
        """JOIN ON clause must only contain r.user_id = i.user_id."""
        query = query_builder.build_query("retention", retention_config)

        # Extract the ON clause
        on_idx = query.index("ON r.user_id = i.user_id")
        # After the ON clause, next line should be GROUP BY (no additional AND conditions)
        after_on = query[on_idx:]
        on_line = after_on.split("\n")[0]

        assert on_line.strip() == "ON r.user_id = i.user_id"

    def test_no_non_equi_in_join_on(self, query_builder, retention_config):
        """JOIN ON must not contain > or < operators between left and right tables."""
        query = query_builder.build_query("retention", retention_config)

        # Find the JOIN ... ON section
        join_idx = query.index("LEFT JOIN return_events r")
        group_idx = query.index("GROUP BY", join_idx)
        join_section = query[join_idx:group_idx]

        # The ON clause should not contain inequality comparisons
        assert "r.ret_ts > i.first_ts" not in join_section
        assert "r.ret_ts < i.first_ts" not in join_section
        assert "r.ret_ts <" not in join_section

    def test_time_window_in_retained_expression(self, query_builder, retention_config):
        """Time-window filter must be inside the IF() aggregation, not the JOIN."""
        query = query_builder.build_query("retention", retention_config)

        # The retained_users expression should contain the time-window check
        assert "IF(r.ret_ts > i.first_ts AND r.ret_ts < i.first_ts + INTERVAL 30 DAY" in query

    def test_no_is_not_null_for_retained(self, query_builder, retention_config):
        """Must not use IS NOT NULL to detect retained users.

        ClickHouse uses default values (epoch 1970-01-01) instead of NULL for
        unmatched LEFT JOIN rows on non-Nullable columns. IS NOT NULL is always
        true, causing every user to be counted as retained.
        """
        query = query_builder.build_query("retention", retention_config)

        assert "IS NOT NULL" not in query


class TestRetentionQueryNoSafeDivide:
    """SAFE_DIVIDE is BigQuery-specific and doesn't exist in ClickHouse."""

    def test_no_safe_divide(self, query_builder, retention_config):
        query = query_builder.build_query("retention", retention_config)

        assert "SAFE_DIVIDE" not in query

    def test_value_uses_guarded_division(self, query_builder, retention_config):
        """Division should be guarded against divide-by-zero."""
        query = query_builder.build_query("retention", retention_config)

        assert "IF(COUNT(DISTINCT i.user_id) = 0, 0," in query


class TestRetentionQueryNoTimestampAdd:
    """TIMESTAMP_ADD is BigQuery-specific. ClickHouse uses arithmetic (+)."""

    def test_no_timestamp_add(self, query_builder, retention_config):
        query = query_builder.build_query("retention", retention_config)

        assert "TIMESTAMP_ADD" not in query

    def test_uses_interval_arithmetic(self, query_builder, retention_config):
        query = query_builder.build_query("retention", retention_config)

        assert "i.first_ts + INTERVAL 30 DAY" in query


class TestRetentionQueryStructure:
    """General structural tests for the retention query."""

    def test_has_initial_cohort_cte(self, query_builder, retention_config):
        query = query_builder.build_query("retention", retention_config)
        assert "initial_cohort AS (" in query

    def test_has_return_events_cte(self, query_builder, retention_config):
        query = query_builder.build_query("retention", retention_config)
        assert "return_events AS (" in query

    def test_selects_cohort_users(self, query_builder, retention_config):
        query = query_builder.build_query("retention", retention_config)
        assert "COUNT(DISTINCT i.user_id) AS cohort_users" in query

    def test_selects_retained_users(self, query_builder, retention_config):
        query = query_builder.build_query("retention", retention_config)
        assert "AS retained_users" in query

    def test_selects_value(self, query_builder, retention_config):
        query = query_builder.build_query("retention", retention_config)
        assert "AS value" in query

    def test_different_window_sizes(self, query_builder):
        for window, expected in [("7d", "INTERVAL 7 DAY"), ("24h", "INTERVAL 24 HOUR"), ("1w", "INTERVAL 1 WEEK")]:
            config = {
                "time_range": {"start": "2026-01-01", "end": "2026-02-01"},
                "granularity": "daily",
                "group_by": [],
                "filters": {},
                "initial_event": {"event_name": "login"},
                "return_event": {"event_name": "purchase"},
                "retention_window": window,
            }
            query = query_builder.build_query("retention", config)
            assert expected in query, f"Expected {expected} for window={window}"
