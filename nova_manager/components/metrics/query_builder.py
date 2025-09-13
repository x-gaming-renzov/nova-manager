import re
from datetime import datetime, timedelta, timezone
from typing import Literal, TypedDict

from nova_manager.components.metrics.artefacts import EventsArtefacts


class KeySource:
    EVENT_PROPERTIES = "event_properties"
    USER_PROFILE = "user_profile"
    USER_EXPERIENCE = "user_experience"


class TimeRange(TypedDict):
    start: str
    end: str


class EventFilter(TypedDict):
    event_name: str
    filters: dict | None


class EnhancedFilterType(TypedDict):
    value: str
    source: str  # KeySource enum value
    op: Literal["=", "!=", ">", "<", ">=", "<="]


class GroupByType(TypedDict):
    key: str
    source: str  # KeySource enum value


class BaseMetricConfig(TypedDict):
    time_range: TimeRange | str
    granularity: Literal["hourly", "daily", "weekly", "monthly", "none"]
    group_by: list[GroupByType]
    filters: dict[str, EnhancedFilterType]


class CountMetricConfig(BaseMetricConfig):
    event_name: str
    distinct: bool


class AggregationMetricConfig(BaseMetricConfig):
    event_name: str
    property: str
    aggregation: Literal["sum", "avg", "min", "max"]


class RatioMetricConfig(BaseMetricConfig):
    numerator: EventFilter
    denominator: EventFilter


class RetentionMetricConfig(BaseMetricConfig):
    initial_event: EventFilter
    return_event: EventFilter
    retention_window: str


GRANULARITY_TRUNC_MAP = {
    "hourly": "TIMESTAMP_TRUNC({ts}, HOUR)",
    "daily": "DATE_TRUNC({ts}, DAY)",
    "weekly": "DATE_TRUNC({ts}, WEEK)",
    "monthly": "DATE_TRUNC({ts}, MONTH)",
    "none": "TIMESTAMP('1970-01-01 00:00:00')",
}

UNIT_SQL_MAP = {
    "h": "HOUR",
    "d": "DAY",
    "w": "WEEK",
    "m": "MONTH",
    "y": "YEAR",
}

CORE_FIELDS = {"event_name", "user_id", "org_id", "app_id"}


class QueryBuilder(EventsArtefacts):
    def build_query(
        self,
        metric_type: Literal["count", "aggregation", "ratio", "retention"],
        metric_config: (
            CountMetricConfig
            | AggregationMetricConfig
            | RatioMetricConfig
            | RetentionMetricConfig
        ),
    ) -> str:
        if metric_type == "count":
            return self._build_count_query(metric_config)

        elif metric_type == "aggregation":
            return self._build_aggregation_query(metric_config)

        elif metric_type == "ratio":
            return self._build_ratio_query(metric_config)

        elif metric_type == "retention":
            return self._build_retention_query(metric_config)

        raise Exception(f"Unsupported metric_type: {metric_type}")

    def _build_count_query(self, metric_config: CountMetricConfig):
        time_range = metric_config["time_range"]
        group_by = metric_config["group_by"]
        filters = metric_config["filters"]

        event_name = metric_config["event_name"]
        distinct = metric_config["distinct"]

        start, end = self._get_start_end(time_range)

        select_parts = self._get_select_parts(metric_config)

        count_expression = (
            "COUNT(DISTINCT e.user_id) AS value" if distinct else "COUNT(*) AS value"
        )
        select_parts.append(count_expression)

        select_expression = "SELECT " + ",\n    ".join(select_parts)

        table_name = self._event_table_name(event_name)
        from_expression = f"FROM `{table_name}` AS e"

        wheres, where_joins = self._wheres_and_joins(event_name, filters)

        where_expression = (
            f"WHERE e.client_ts >= '{start}' AND e.client_ts < '{end}'"
            + (" AND " + " AND ".join(wheres) if wheres else "")
        )

        group_props_join_expression = self._group_props_join_expression(
            event_name, group_by
        )

        join_expression = "\n".join(where_joins + group_props_join_expression)

        group_by_keys = [item["key"] for item in group_by]
        group_by_expression = "GROUP BY " + ", ".join(["period"] + group_by_keys)

        order_expression = "ORDER BY period"

        return self._format_query(
            select_expression,
            from_expression,
            join_expression=join_expression,
            where_expression=where_expression,
            group_by_expression=group_by_expression,
            order_expression=order_expression,
        )

    def _build_aggregation_query(self, metric_config: AggregationMetricConfig):
        time_range = metric_config["time_range"]
        group_by = metric_config["group_by"]
        filters = metric_config["filters"]

        event_name = metric_config["event_name"]
        aggregation = metric_config["aggregation"]
        property = metric_config["property"]

        start, end = self._get_start_end(time_range)

        select_parts = self._get_select_parts(metric_config)

        aggregation_expression = (
            f"{aggregation.upper()}(CAST(p_val.value AS FLOAT64)) AS value"
        )
        select_parts.append(aggregation_expression)

        select_expression = "SELECT " + ",\n    ".join(select_parts)

        table_name = self._event_table_name(event_name)
        from_expression = f"FROM `{table_name}` AS e"

        property_join_expression = self._props_join_expression(
            event_name, "p_val", property
        )

        wheres, where_joins = self._wheres_and_joins(event_name, filters)

        where_expression = (
            f"WHERE e.client_ts >= '{start}' AND e.client_ts < '{end}'"
            + (" AND " + " AND ".join(wheres) if wheres else "")
        )

        group_props_join_expression = self._group_props_join_expression(
            event_name, group_by
        )

        # Combine WHERE joins, group property joins, and the property join into one list
        join_expression = "\n".join(
            where_joins + group_props_join_expression + [property_join_expression]
        )

        group_by_keys = [item["key"] for item in group_by]
        group_by_expression = "GROUP BY " + ", ".join(["period"] + group_by_keys)

        return self._format_query(
            select_expression,
            from_expression,
            join_expression=join_expression,
            where_expression=where_expression,
            group_by_expression=group_by_expression,
        )

    def _build_ratio_query(self, metric_config: RatioMetricConfig):
        granularity = metric_config["granularity"]
        time_range = metric_config["time_range"]
        group_by = metric_config["group_by"]
        filters = metric_config["filters"]

        numerator_config = metric_config["numerator"]
        numerator_filters = numerator_config.get("filters") or {}
        numerator_filters.update(filters)

        numerator_expression = self._build_count_query(
            {
                "event_name": numerator_config["event_name"],
                "distinct": False,
                "time_range": time_range,
                "granularity": granularity,
                "group_by": group_by,
                "filters": numerator_filters,
            }
        )

        denominator_config = metric_config["denominator"]
        denominator_filters = denominator_config.get("filters") or {}
        denominator_filters.update(filters)

        denominator_expression = self._build_count_query(
            {
                "event_name": denominator_config["event_name"],
                "distinct": False,
                "time_range": time_range,
                "granularity": granularity,
                "group_by": group_by,
                "filters": denominator_filters,
            }
        )

        with_expression = f"WITH\n num AS (\n{numerator_expression}\n),\n den AS (\n{denominator_expression}\n)"

        # Extract keys from group_by
        group_by_keys = [item["key"] for item in group_by]

        select_parts = [
            "num.period AS period",
            "SAFE_DIVIDE(num.value, den.value) AS value",
        ] + [f"num.{c}" for c in group_by_keys]
        select_expression = "SELECT " + ",\n    ".join(select_parts)

        from_expression = "FROM num"

        group_by_join_conditions = [
            f"IFNULL(num.{c},'') = IFNULL(den.{c},'')" for c in group_by_keys
        ]
        join_conditions = ["num.period = den.period"] + group_by_join_conditions
        join_expression = "JOIN den ON " + " AND ".join(join_conditions)

        order_by_expression = "ORDER BY num.period"

        return self._format_query(
            select_expression,
            from_expression,
            join_expression=join_expression,
            order_expression=order_by_expression,
            with_expression=with_expression,
        )

    # TODO: Review this query
    def _build_retention_query(self, metric_config: RetentionMetricConfig):
        granularity = metric_config["granularity"]
        time_range = metric_config["time_range"]
        group_by = metric_config["group_by"]
        filters = metric_config["filters"]

        initial_event = metric_config["initial_event"]
        return_event = metric_config["return_event"]
        retention_window = metric_config["retention_window"]

        start, end = self._get_start_end(time_range)

        window_sql = self._interval_sql(retention_window)
        bucket_expr = self._time_bucket("e.client_ts", granularity)

        # Initial cohort CTE
        initial_event_name = initial_event["event_name"]
        initial_filters = initial_event.get("filters") or {}
        initial_filters.update(filters)

        g_selects = self._group_selects(group_by, "e")
        g_joins = self._group_props_join_expression(initial_event_name, group_by)
        f_where_init, f_joins_init = self._wheres_and_joins(
            initial_event_name, initial_filters
        )

        init_select_cols = (
            [f"{bucket_expr} AS cohort_period"]
            + g_selects
            + [
                "e.user_id AS user_id",
                "MIN(e.client_ts) AS first_ts",
            ]
        )

        # Extract keys from group_by
        group_by_keys = [item["key"] for item in group_by]

        init_group_clause = ", ".join(["cohort_period", "user_id"] + group_by_keys)

        init_cte = (
            "initial_cohort AS (\n    SELECT\n        "
            + ",\n        ".join(init_select_cols)
            + f"\n    FROM `{self._event_table_name(initial_event_name)}` AS e\n    "
            + "\n    ".join(g_joins + f_joins_init)
            + f"\n    WHERE e.client_ts >= '{start}' AND e.client_ts < '{end}'{' AND ' + ' AND '.join(f_where_init) if f_where_init else ''}\n"
            + f"    GROUP BY {init_group_clause}\n)"
        )

        # Return events CTE
        return_event_name = return_event["event_name"]
        return_filters = return_event.get("filters") or {}
        return_filters.update(filters)

        f_where_ret, f_joins_ret = self._wheres_and_joins(
            return_event_name, return_filters
        )
        ret_cte = (
            "return_events AS (\n    SELECT\n        r.user_id AS user_id,\n        r.client_ts AS ret_ts\n    FROM "
            + f"`{self._event_table_name(return_event_name)}`"
            + " AS r\n    "
            + "\n    ".join(f_joins_ret)
            + f"\n    WHERE r.client_ts >= '{start}' AND r.client_ts < '{end}'{' AND ' + ' AND '.join(f_where_ret) if f_where_ret else ''}\n)"
        )

        # Final select
        select_cols = ["i.cohort_period AS period"] + [f"i.{c}" for c in group_by_keys]
        group_by_cols = ["i.cohort_period"] + group_by_keys
        select_list = ", ".join(select_cols)
        group_clause = ", ".join(group_by_cols)

        final_sql = (
            "SELECT\n    "
            + select_list
            + ",\n    COUNT(DISTINCT i.user_id) AS cohort_users,\n    COUNT(DISTINCT IF(r.ret_ts IS NOT NULL, i.user_id, NULL)) AS retained_users,\n    SAFE_DIVIDE(COUNT(DISTINCT IF(r.ret_ts IS NOT NULL, i.user_id, NULL)), COUNT(DISTINCT i.user_id)) AS value"
            + f"\nFROM initial_cohort i\nLEFT JOIN return_events r\n  ON r.user_id = i.user_id\n  AND r.ret_ts > i.first_ts\n  AND r.ret_ts < TIMESTAMP_ADD(i.first_ts, {window_sql})\nGROUP BY {group_clause}\nORDER BY i.cohort_period"
        )

        return f"WITH\n{init_cte},\n{ret_cte}\n{final_sql}"

    def _format_query(
        self,
        select_expression: str,
        from_expression: str,
        join_expression: str | None = None,
        where_expression: str | None = None,
        group_by_expression: str | None = None,
        order_expression: str | None = None,
        with_expression: str | None = None,
    ) -> str:
        query = f"{select_expression}\n{from_expression}"

        if join_expression:
            query += f"\n{join_expression}"

        if where_expression:
            query += f"\n{where_expression}"

        if group_by_expression:
            query += f"\n{group_by_expression}"

        if order_expression:
            query += f"\n{order_expression}"

        if with_expression:
            query = f"{with_expression}\n" + query

        return query

    def _time_bucket(self, column_name: str, granularity: str) -> str:
        if granularity not in GRANULARITY_TRUNC_MAP:
            raise ValueError(f"Unsupported time granularity: {granularity}")

        return GRANULARITY_TRUNC_MAP[granularity].format(ts=column_name)

    def _get_select_parts(self, metric_config: BaseMetricConfig):
        granularity = metric_config["granularity"]
        group_by = metric_config["group_by"]

        time_bucket = self._time_bucket("e.client_ts", granularity)
        group_selects = self._group_selects(group_by, "e")

        period_expression = f"{time_bucket} AS period"

        return [period_expression] + group_selects

    def _group_selects(
        self, group_by: list[GroupByType], event_table_alias: str
    ) -> list[str]:
        selects = []

        for item in group_by:
            key = item["key"]
            source = item.get("source")

            if key in CORE_FIELDS:
                selects.append(f"{event_table_alias}.{key} AS {key}")
            else:
                # Support multiple sources for grouped keys.
                # For event properties we use alias ep_{key} (joined by _props_join_expression)
                if source == KeySource.EVENT_PROPERTIES:
                    selects.append(f"ep_{key}.value AS {key}")
                elif source == KeySource.USER_PROFILE:
                    selects.append(f"val_{key}.value AS {key}")
                elif source == KeySource.USER_EXPERIENCE:
                    # user_experience join aliases use ue_{key} and expose the column directly
                    selects.append(f"ue_{key}.{key} AS {key}")
                else:
                    selects.append(f"val_{key}.value AS {key}")

        return selects

    def _props_join_expression(self, event_name: str, alias: str, key: str):
        """Return LEFT JOIN clause for a specific property key."""

        return (
            f"LEFT JOIN `{self._event_props_table_name(event_name)}` AS {alias} "
            f"ON e.event_id = {alias}.event_id AND {alias}.key = '{key}'"
        )

    def _user_profile_join_expression(self, alias: str, key: str) -> str:
        """Return LEFT JOIN clause for user profile properties using only the latest value."""
        # Use a subquery to get only the most recent user profile value for each user
        return (
            f"LEFT JOIN ("
            f"  SELECT user_id, key, value, "
            f"  ROW_NUMBER() OVER (PARTITION BY user_id, key ORDER BY server_ts DESC) as rn "
            f"  FROM `{self._user_profile_props_table_name()}` "
            f"  WHERE key = '{key}'"
            f") AS {alias} "
            f"ON e.user_id = {alias}.user_id AND {alias}.key = '{key}' AND {alias}.rn = 1"
        )

    def _user_experience_join_expression(self, alias: str, key: str) -> str:
        """Return LEFT JOIN clause for the latest user_experience values per user.

        This returns a LEFT JOIN on a subquery that selects user_id, the requested
        column (key) and a ROW_NUMBER() partitioned by user_id ordered by assigned_at DESC
        so that rn = 1 yields the latest assignment per user.
        """
        # Note: Uses the user_experience table name from EventsArtefacts
        return (
            f"LEFT JOIN ("
            f"  SELECT user_id, {key}, ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY assigned_at DESC) as rn "
            f"  FROM `{self._user_experience_table_name()}` "
            f") AS {alias} "
            f"ON e.user_id = {alias}.user_id AND {alias}.rn = 1"
        )

    def _group_props_join_expression(
        self, event_name: str, group_by: list[GroupByType]
    ) -> list[str]:
        joins = []

        for item in group_by:
            key = item["key"]
            source = item["source"]

            if key not in CORE_FIELDS:
                # Choose alias and join helper depending on source
                if source == KeySource.EVENT_PROPERTIES:
                    alias = f"ep_{key}"
                    joins.append(self._props_join_expression(event_name, alias, key))
                elif source == KeySource.USER_EXPERIENCE:
                    alias = f"ue_{key}"
                    joins.append(self._user_experience_join_expression(alias, key))
                else:  # User Profile (default)
                    alias = f"val_{key}"
                    joins.append(self._user_profile_join_expression(alias, key))

        return joins

    def _wheres_and_joins(
        self, event_name: str, filters: dict[str, EnhancedFilterType] | None
    ) -> tuple[list[str], list[str]]:
        """Generate SQL WHERE snippets and JOIN clauses for filters."""
        filters = filters or {}
        joins = []
        wheres = []

        for key, filter_data in filters.items():
            value = filter_data["value"]
            source = filter_data["source"]
            op = filter_data["op"]

            if key in CORE_FIELDS:
                wheres.append(f"e.{key} {op} '{value}'")
            elif source == KeySource.EVENT_PROPERTIES:
                alias = f"ep_{key}"
                joins.append(self._props_join_expression(event_name, alias, key))
                wheres.append(f"{alias}.value {op} '{value}'")
            else:  # User Profile
                # Support user_experience (personalisation) as a source too
                if source == KeySource.USER_EXPERIENCE:
                    alias = f"ue_{key}"
                    joins.append(self._user_experience_join_expression(alias, key))
                    # user_experience exposes the column directly (e.g. personalisation_id)
                    wheres.append(f"{alias}.{key} {op} '{value}'")
                else:
                    alias = f"up_{key}"
                    joins.append(self._user_profile_join_expression(alias, key))
                    wheres.append(f"{alias}.value {op} '{value}'")

        return wheres, joins

    def _get_start_end(self, time_range: TimeRange | str) -> tuple[str, str]:
        if isinstance(time_range, str):
            qty, unit = self._parse_interval_string(time_range)

            # Get current UTC time
            end_time = datetime.now(timezone.utc)

            # Calculate start time by subtracting the interval
            if unit == "h":
                start_time = end_time - timedelta(hours=qty)
            elif unit == "d":
                start_time = end_time - timedelta(days=qty)
            elif unit == "w":
                start_time = end_time - timedelta(weeks=qty)
            elif unit == "m":
                # Approximate months as 30 days
                start_time = end_time - timedelta(days=qty * 30)
            elif unit == "y":
                # Approximate years as 365 days
                start_time = end_time - timedelta(days=qty * 365)
            else:
                raise ValueError(f"Unsupported time unit: {unit}")

            return start_time.isoformat(), end_time.isoformat()
        else:
            if "start" not in time_range or "end" not in time_range:
                raise ValueError("Invalid time range")

            return time_range["start"], time_range["end"]

    def _parse_interval_string(self, interval_str: str) -> tuple[int, str]:
        m = re.fullmatch(r"(\d+)([hdwmy])", interval_str.strip().lower())

        if not m:
            raise ValueError(
                f"Invalid interval format: {interval_str}. Use forms like '7d', '24h', '1w'"
            )

        return int(m.group(1)), m.group(2)

    def _interval_sql(self, interval_str: str) -> str:
        """Convert a simple interval string (e.g. '7d', '24h', '1w') to BigQuery INTERVAL SQL."""
        qty, unit = self._parse_interval_string(interval_str)

        unit_sql = UNIT_SQL_MAP[unit]

        return f"INTERVAL {qty} {unit_sql}"
