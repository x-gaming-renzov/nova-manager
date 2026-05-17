"""KQL (Kusto Query Language) query builder for Azure Data Explorer.

Parallel implementation to query_builder.py (ClickHouse SQL).
Uses per-org/app databases, same architecture as ClickHouse.
Table names are plain (raw_events, event_props, etc.) — database
scoping is handled by ADXService targeting the correct database.
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Literal

from nova_manager.components.metrics.artefacts import EventsArtefacts
from nova_manager.components.metrics.query_builder import (
    BaseMetricConfig,
    CountMetricConfig,
    AggregationMetricConfig,
    RatioMetricConfig,
    RetentionMetricConfig,
    OperationalMetricConfig,
    FormulaMetricConfig,
    FormulaOperand,
    GroupByType,
    EnhancedFilterType,
    KeySource,
    CORE_FIELDS,
)

# KQL time bin expressions
KQL_GRANULARITY_MAP = {
    "hourly": "bin({ts}, 1h)",
    "daily": "bin({ts}, 1d)",
    "weekly": "startofweek({ts})",
    "monthly": "startofmonth({ts})",
    "none": "datetime(1970-01-01)",
}

KQL_UNIT_MAP = {
    "h": "h",
    "d": "d",
    "w": "d",  # KQL has no week timespan literal; we multiply by 7
    "m": "d",  # approximate months as 30d
    "y": "d",  # approximate years as 365d
}

# Columns in business_metrics that can be filtered/grouped
_BUSINESS_METRIC_COLUMNS = {"dimension", "currency", "metric_name"}


class KQLQueryBuilder(EventsArtefacts):
    """Generates KQL queries for Azure Data Explorer.

    Same public interface as QueryBuilder (ClickHouse):
        build_query(metric_type, metric_config) -> str
    """

    # ── Table name overrides ──────────────────────────────────
    # KQL targets the database at the service level, so table names
    # are plain (no database prefix like ClickHouse's org_x_app_y.table).

    def _raw_events_table_name(self) -> str:
        return "raw_events"

    def _event_props_table_name(self) -> str:
        return "event_props"

    def _user_profile_props_table_name(self) -> str:
        return "user_profile_props"

    def _user_experience_table_name(self) -> str:
        return "user_experience"

    def _business_metrics_table_name(self) -> str:
        return "business_metrics"

    def build_query(
        self,
        metric_type: Literal["count", "aggregation", "ratio", "retention", "operational", "formula"],
        metric_config: (
            CountMetricConfig
            | AggregationMetricConfig
            | RatioMetricConfig
            | RetentionMetricConfig
            | OperationalMetricConfig
            | FormulaMetricConfig
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
        elif metric_type == "operational":
            return self._build_operational_query(metric_config)
        elif metric_type == "formula":
            return self._build_formula_query(metric_config)
        raise Exception(f"Unsupported metric_type: {metric_type}")

    # ── Count ──────────────────────────────────────────────────

    def _build_count_query(self, config: CountMetricConfig) -> str:
        event_name = self._safe_identifier(config["event_name"], "event_name")
        distinct = config["distinct"]
        start, end = self._get_start_end(config["time_range"])
        group_by = config["group_by"]
        filters = config["filters"]

        agg = f"dcount(user_id)" if distinct else "count()"
        bucket = self._time_bucket("client_ts", config["granularity"])

        lines = [f"{self._raw_events_table_name()}"]

        # Joins first (must come before where in KQL pipe)
        join_lines = self._build_joins(event_name, group_by, filters)
        lines.extend(join_lines)

        # Where
        where_parts = [
            f"event_name == '{event_name}'",
            f"client_ts >= datetime({start})",
            f"client_ts < datetime({end})",
        ]
        where_parts.extend(self._build_filter_wheres(filters))
        lines.append(f"| where {' and '.join(where_parts)}")

        # Summarize
        summarize_by = [f"period = {bucket}"]
        summarize_by.extend(self._group_by_columns(group_by))
        lines.append(f"| summarize value = {agg} by {', '.join(summarize_by)}")

        lines.append("| order by period asc")

        return "\n".join(lines)

    # ── Aggregation ────────────────────────────────────────────

    def _build_aggregation_query(self, config: AggregationMetricConfig) -> str:
        event_name = self._safe_identifier(config["event_name"], "event_name")
        aggregation = config["aggregation"]
        prop = config["property"]
        start, end = self._get_start_end(config["time_range"])
        group_by = config["group_by"]
        filters = config["filters"]

        bucket = self._time_bucket("client_ts", config["granularity"])

        lines = [f"{self._raw_events_table_name()}"]

        # Join event_props for the property value
        join_lines = self._build_joins(event_name, group_by, filters)
        lines.extend(join_lines)
        lines.append(
            f"| join kind=leftouter ("
            f"{self._event_props_table_name()} | where event_name == '{event_name}' and key == '{prop}'"
            f" | project event_id, prop_value = value"
            f") on event_id"
        )

        # Where
        where_parts = [
            f"event_name == '{event_name}'",
            f"client_ts >= datetime({start})",
            f"client_ts < datetime({end})",
        ]
        where_parts.extend(self._build_filter_wheres(filters))
        lines.append(f"| where {' and '.join(where_parts)}")

        # Summarize
        agg_expr = f"{aggregation}(todouble(prop_value))"
        summarize_by = [f"period = {bucket}"]
        summarize_by.extend(self._group_by_columns(group_by))
        lines.append(f"| summarize value = {agg_expr} by {', '.join(summarize_by)}")

        lines.append("| order by period asc")

        return "\n".join(lines)

    # ── Ratio ──────────────────────────────────────────────────

    def _build_ratio_query(self, config: RatioMetricConfig) -> str:
        granularity = config["granularity"]
        time_range = config["time_range"]
        group_by = config["group_by"]
        filters = config["filters"]

        num_config = config["numerator"]
        num_filters = {**(num_config.get("filters") or {}), **filters}
        num_query = self._build_count_query({
            "event_name": num_config["event_name"],
            "distinct": num_config.get("distinct", False),
            "time_range": time_range,
            "granularity": granularity,
            "group_by": group_by,
            "filters": num_filters,
        })

        den_config = config["denominator"]
        den_filters = {**(den_config.get("filters") or {}), **filters}
        den_query = self._build_count_query({
            "event_name": den_config["event_name"],
            "distinct": den_config.get("distinct", False),
            "time_range": time_range,
            "granularity": granularity,
            "group_by": group_by,
            "filters": den_filters,
        })

        group_by_keys = [item["key"] for item in group_by]

        lines = [
            f"let num = ({num_query});",
            f"let den = ({den_query});",
            "num",
            f"| join kind=inner (den) on period{self._join_on_keys(group_by_keys)}",
        ]

        project_parts = ["period"]
        project_parts.extend(group_by_keys)
        project_parts.append("value = iff(value1 == 0, real(null), todouble(value) / todouble(value1))")

        lines.append(f"| project {', '.join(project_parts)}")
        lines.append("| order by period asc")

        return "\n".join(lines)

    # ── Retention ──────────────────────────────────────────────

    def _build_retention_query(self, config: RetentionMetricConfig) -> str:
        granularity = config["granularity"]
        time_range = config["time_range"]
        group_by = config["group_by"]
        filters = config["filters"]

        initial_event = config["initial_event"]
        return_event = config["return_event"]
        retention_window = config["retention_window"]

        start, end = self._get_start_end(time_range)
        window_ts = self._kql_timespan(retention_window)
        bucket = self._time_bucket("client_ts", granularity)

        # Initial event name
        init_event_name = self._safe_identifier(
            initial_event["event_name"], "initial_event.event_name"
        )
        init_filters = initial_event.get("filters") or {}
        init_filters.update(filters)

        # Return event name
        ret_event_name = self._safe_identifier(
            return_event["event_name"], "return_event.event_name"
        )
        ret_filters = return_event.get("filters") or {}
        ret_filters.update(filters)

        group_by_keys = [item["key"] for item in group_by]

        # Initial cohort
        init_where = [
            f"event_name == '{init_event_name}'",
            f"client_ts >= datetime({start})",
            f"client_ts < datetime({end})",
        ]
        init_where.extend(self._build_filter_wheres(init_filters))
        init_joins = self._build_joins(init_event_name, group_by, init_filters)

        init_summarize_by = ["cohort_period = " + bucket, "user_id"]
        init_summarize_by.extend(group_by_keys)
        # For group-by on joined sources, we need to add them to summarize
        init_group_selects = self._group_by_columns(group_by)

        init_lines = [f"{self._raw_events_table_name()}"]
        init_lines.extend(init_joins)
        init_lines.append(f"| where {' and '.join(init_where)}")
        init_summarize_cols = ["first_ts = min(client_ts)"]
        init_lines.append(
            f"| summarize {', '.join(init_summarize_cols)} by {', '.join(init_summarize_by)}"
        )
        init_query = "\n".join(init_lines)

        # Return events
        ret_where = [
            f"event_name == '{ret_event_name}'",
            f"client_ts >= datetime({start})",
            f"client_ts < datetime({end})",
        ]
        ret_where.extend(self._build_filter_wheres(ret_filters))
        ret_joins = self._build_joins(ret_event_name, [], ret_filters)

        ret_lines = [f"{self._raw_events_table_name()}"]
        ret_lines.extend(ret_joins)
        ret_lines.append(f"| where {' and '.join(ret_where)}")
        ret_lines.append("| project user_id, ret_ts = client_ts")
        ret_query = "\n".join(ret_lines)

        # Final query
        group_cols = ["cohort_period"] + group_by_keys
        project_group = ["period = cohort_period"] + group_by_keys

        lines = [
            f"let initial_cohort = ({init_query});",
            f"let return_events = ({ret_query});",
            "initial_cohort",
            "| join kind=leftouter (return_events) on user_id",
            f"| summarize "
            f"cohort_users = dcount(user_id), "
            f"retained_users = dcountif(user_id, ret_ts > first_ts and ret_ts < first_ts + {window_ts}), "
            f"value = todouble(dcountif(user_id, ret_ts > first_ts and ret_ts < first_ts + {window_ts})) "
            f"/ todouble(dcount(user_id)) "
            f"by {', '.join(group_cols)}",
        ]
        lines.append(f"| project {', '.join(project_group)}, cohort_users, retained_users, value")
        lines.append("| order by period asc")

        return "\n".join(lines)

    # ── Operational ────────────────────────────────────────────

    def _build_operational_query(self, config: OperationalMetricConfig) -> str:
        time_range = config["time_range"]
        granularity = config["granularity"]
        group_by = config.get("group_by", [])
        filters = config.get("filters") or {}
        metric_name = self._safe_identifier(config["metric_name"], "metric_name")
        dimension_filter = config.get("dimension_filter")
        if dimension_filter:
            dimension_filter = self._safe_identifier(dimension_filter, "dimension_filter")
        aggregation = config.get("aggregation", "sum")
        if aggregation not in {"sum", "avg", "min", "max"}:
            raise ValueError(f"Invalid aggregation: {aggregation}")

        start, end = self._get_start_end(time_range)
        bucket = self._time_bucket("period_start", granularity)

        where_parts = [
            f"metric_name == '{metric_name}'",
            f"period_start >= datetime({start})",
            f"period_start < datetime({end})",
        ]

        if dimension_filter:
            where_parts.append(f"dimension == '{dimension_filter}'")

        scenario_id = config.get("scenario_id")
        if scenario_id:
            scenario_id = self._safe_identifier(scenario_id, "scenario_id")
            where_parts.append(f"scenario_id == '{scenario_id}'")

        # Apply filters on business_metrics columns
        ALLOWED_OPS = {"==", "!=", ">", "<", ">=", "<="}
        OP_MAP = {"=": "=="}  # Map SQL = to KQL ==
        for key, filter_data in filters.items():
            if key in _BUSINESS_METRIC_COLUMNS:
                value = self._escape_kql_string(filter_data["value"])
                op = filter_data.get("op", "=")
                kql_op = OP_MAP.get(op, op)
                if kql_op not in ALLOWED_OPS:
                    raise ValueError(f"Unsupported filter operator: {op!r}")
                self._safe_identifier(key, "filter key")
                where_parts.append(f"{key} {kql_op} '{value}'")

        group_by_keys = []
        for item in group_by:
            key = item["key"]
            if key in _BUSINESS_METRIC_COLUMNS:
                group_by_keys.append(key)

        summarize_by = [f"period = {bucket}"] + group_by_keys

        # ADX: for ReplacingMergeTree equivalent, use arg_max to deduplicate
        # business_metrics uses (metric_name, dimension, period_start, scenario_id) as dedup key
        # We summarize with arg_max(value, created_at) to get the latest value per dedup key,
        # then re-aggregate with the requested aggregation.
        lines = [f"{self._business_metrics_table_name()}"]
        lines.append(f"| where {' and '.join(where_parts)}")
        # Dedup: get latest row per (metric_name, dimension, period_start, scenario_id)
        lines.append(
            "| summarize value = arg_max(created_at, value) by metric_name, dimension, period_start, scenario_id"
        )
        lines.append("| project metric_name, dimension, value = value1, period_start, scenario_id")
        # Now aggregate
        lines.append(
            f"| summarize value = {aggregation}(value) by {', '.join(summarize_by)}"
        )
        lines.append("| order by period asc")

        return "\n".join(lines)

    # ── Formula ────────────────────────────────────────────────

    def _build_formula_query(self, config: FormulaMetricConfig) -> str:
        time_range = config["time_range"]
        granularity = config["granularity"]
        group_by = config.get("group_by", [])
        operands = config["operands"]
        expression = config["expression"]

        if not operands:
            raise ValueError("Formula metric must have at least one operand")

        for name, operand in operands.items():
            if operand["type"] == "formula":
                raise ValueError(
                    f"Operand '{name}' cannot be of type 'formula' (no nesting)"
                )

        operand_names = list(operands.keys())
        safe_expr = self._safe_parse_expression(expression, operand_names)

        # Build let statements
        let_parts = []
        for name, operand in operands.items():
            op_config = dict(operand["config"])
            op_config["time_range"] = time_range
            op_config["granularity"] = granularity
            if operand["type"] == "operational":
                op_group_by = [g for g in group_by if g["key"] in _BUSINESS_METRIC_COLUMNS]
            else:
                op_group_by = group_by
            op_config.setdefault("group_by", op_group_by)
            op_config.setdefault("filters", {})
            sub_query = self.build_query(operand["type"], op_config)
            let_parts.append(f"let op_{name} = ({sub_query});")

        # Determine group_by_keys from first operand
        first_name = operand_names[0]
        first_type = operands[first_name]["type"]
        if first_type == "operational":
            group_by_keys = [item["key"] for item in group_by if item["key"] in _BUSINESS_METRIC_COLUMNS]
        else:
            group_by_keys = [item["key"] for item in group_by]

        # In KQL, after joins the "value" column from each table gets suffixed:
        # first table: value, second: value1, third: value2, etc.
        # Build a mapping from op_{name}.value -> the positional column name.
        value_col_map = {}
        for idx, name in enumerate(operand_names):
            if idx == 0:
                value_col_map[f"op_{name}.value"] = "value"
            else:
                value_col_map[f"op_{name}.value"] = f"value{idx}"

        # Rewrite the expression to use positional column names
        kql_expr = safe_expr
        for ref, col in value_col_map.items():
            kql_expr = kql_expr.replace(ref, col)

        lines = list(let_parts)
        lines.append(f"op_{first_name}")

        # Join remaining operands
        for name in operand_names[1:]:
            join_on = "period"
            if group_by_keys:
                join_on += ", " + ", ".join(group_by_keys)
            lines.append(
                f"| join kind=inner (op_{name}) on {join_on}"
            )

        # Project final result
        project_parts = ["period"] + group_by_keys + [f"value = {kql_expr}"]
        lines.append(f"| project {', '.join(project_parts)}")
        lines.append(f"| order by period asc")

        return "\n".join(lines)

    # ── Helpers ─────────────────────────────────────────────────

    @staticmethod
    def _safe_identifier(value: str, field_name: str) -> str:
        if not re.fullmatch(r"[a-zA-Z0-9_.\-]+", value):
            raise ValueError(
                f"Unsafe characters in {field_name}: {value!r}. "
                f"Only alphanumeric, underscore, hyphen, and dot allowed."
            )
        return value

    @staticmethod
    def _escape_kql_string(value: str) -> str:
        return str(value).replace("\\", "\\\\").replace("'", "\\'")

    def _time_bucket(self, column: str, granularity: str) -> str:
        if granularity not in KQL_GRANULARITY_MAP:
            raise ValueError(f"Unsupported time granularity: {granularity}")
        return KQL_GRANULARITY_MAP[granularity].format(ts=column)

    def _get_start_end(self, time_range) -> tuple[str, str]:
        if isinstance(time_range, str):
            qty, unit = self._parse_interval_string(time_range)
            end_time = datetime.now(timezone.utc)

            if unit == "h":
                start_time = end_time - timedelta(hours=qty)
            elif unit == "d":
                start_time = end_time - timedelta(days=qty)
            elif unit == "w":
                start_time = end_time - timedelta(weeks=qty)
            elif unit == "m":
                start_time = end_time - timedelta(days=qty * 30)
            elif unit == "y":
                start_time = end_time - timedelta(days=qty * 365)
            else:
                raise ValueError(f"Unsupported time unit: {unit}")

            fmt = "%Y-%m-%d %H:%M:%S"
            return start_time.strftime(fmt), end_time.strftime(fmt)
        else:
            if "start" not in time_range or "end" not in time_range:
                raise ValueError("Invalid time range")

            start_str = str(time_range["start"])
            end_str = str(time_range["end"])
            ts_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}:\d{2})?$")
            if not ts_pattern.match(start_str):
                raise ValueError(f"Invalid start date format: {start_str!r}")
            if not ts_pattern.match(end_str):
                raise ValueError(f"Invalid end date format: {end_str!r}")

            return start_str, end_str

    @staticmethod
    def _parse_interval_string(interval_str: str) -> tuple[int, str]:
        m = re.fullmatch(r"(\d+)([hdwmy])", interval_str.strip().lower())
        if not m:
            raise ValueError(
                f"Invalid interval format: {interval_str}. Use forms like '7d', '24h', '1w'"
            )
        return int(m.group(1)), m.group(2)

    def _kql_timespan(self, interval_str: str) -> str:
        """Convert interval string to KQL timespan literal."""
        qty, unit = self._parse_interval_string(interval_str)
        if unit == "h":
            return f"{qty}h"
        elif unit == "d":
            return f"{qty}d"
        elif unit == "w":
            return f"{qty * 7}d"
        elif unit == "m":
            return f"{qty * 30}d"
        elif unit == "y":
            return f"{qty * 365}d"
        raise ValueError(f"Unsupported unit: {unit}")

    def _group_by_columns(self, group_by: list[GroupByType]) -> list[str]:
        """Return column references for summarize ... by clause."""
        cols = []
        for item in group_by:
            key = item["key"]
            source = item.get("source")
            if key in CORE_FIELDS:
                cols.append(key)
            elif source == KeySource.EVENT_PROPERTIES:
                # After join, the key column from event_props becomes available
                cols.append(key)
            elif source == KeySource.USER_EXPERIENCE:
                cols.append(key)
            else:
                # user_profile — after join, value column from user_profile_props
                cols.append(key)
        return cols

    def _build_joins(
        self,
        event_name: str,
        group_by: list[GroupByType],
        filters: dict[str, EnhancedFilterType] | None,
    ) -> list[str]:
        """Build KQL join pipes for group_by and filter sources."""
        joins = []
        joined_keys = set()
        filters = filters or {}

        # Group-by joins
        for item in group_by:
            key = item["key"]
            source = item.get("source", "")
            if key in CORE_FIELDS or key in joined_keys:
                continue

            join_line = self._join_for_source(event_name, key, source)
            if join_line:
                joins.append(join_line)
                joined_keys.add(key)

        # Filter joins
        for key, filter_data in filters.items():
            if key in CORE_FIELDS or key in joined_keys:
                continue
            source = filter_data.get("source", "")
            join_line = self._join_for_source(event_name, key, source)
            if join_line:
                joins.append(join_line)
                joined_keys.add(key)

        return joins

    def _join_for_source(self, event_name: str, key: str, source: str) -> str | None:
        """Return a KQL join pipe for a specific source type."""
        if source == KeySource.EVENT_PROPERTIES:
            return (
                f"| join kind=leftouter ("
                f"{self._event_props_table_name()} "
                f"| where event_name == '{event_name}' and key == '{key}' "
                f"| project event_id, {key} = value"
                f") on event_id"
            )
        elif source == KeySource.USER_EXPERIENCE:
            return (
                f"| join kind=leftouter ("
                f"{self._user_experience_table_name()} "
                f"| summarize arg_max(assigned_at, {key}) by user_id "
                f"| project user_id, {key} = {key}1"
                f") on user_id"
            )
        elif source == KeySource.USER_PROFILE:
            return (
                f"| join kind=leftouter ("
                f"{self._user_profile_props_table_name()} "
                f"| where key == '{key}' "
                f"| summarize arg_max(server_ts, value) by user_id "
                f"| project user_id, {key} = value1"
                f") on user_id"
            )
        return None

    def _build_filter_wheres(self, filters: dict[str, EnhancedFilterType] | None) -> list[str]:
        """Generate KQL where conditions for filters."""
        if not filters:
            return []

        wheres = []
        ALLOWED_OPS = {"==", "!=", ">", "<", ">=", "<="}
        OP_MAP = {"=": "=="}

        for key, filter_data in filters.items():
            value = self._escape_kql_string(filter_data["value"])
            op = filter_data["op"]
            kql_op = OP_MAP.get(op, op)
            if kql_op not in ALLOWED_OPS:
                raise ValueError(f"Unsupported filter operator: {op!r}")
            self._safe_identifier(key, "filter key")

            if key in CORE_FIELDS:
                wheres.append(f"{key} {kql_op} '{value}'")
            else:
                # After join, the key is available as a column
                wheres.append(f"{key} {kql_op} '{value}'")

        return wheres

    def _join_on_keys(self, keys: list[str]) -> str:
        """Build KQL join on clause for additional keys beyond period."""
        if not keys:
            return ""
        return ", " + ", ".join(keys)

    @staticmethod
    def _safe_parse_expression(expression: str, operand_names: list[str]) -> str:
        """Parse and validate a formula expression, returning safe KQL.

        Same validation as ClickHouse version. Replaces operand names with
        op_{name} value references and wraps division with iff(x==0, ...).

        After KQL joins, value columns are: value (first), value1 (second), etc.
        We reference them as op_{name} table names in let statements.
        """
        tokens = re.findall(r"[a-zA-Z_]\w*|[+\-*/()]|\d+(?:\.\d+)?", expression)

        allowed_operators = {"+", "-", "*", "/", "(", ")"}
        numeric_pattern = re.compile(r"^\d+(\.\d+)?$")

        validated_tokens = []
        for token in tokens:
            if token in operand_names:
                validated_tokens.append(f"op_{token}.value")
            elif token in allowed_operators:
                validated_tokens.append(token)
            elif numeric_pattern.match(token):
                validated_tokens.append(token)
            else:
                raise ValueError(
                    f"Invalid token in formula expression: '{token}'. "
                    f"Allowed: operand names ({', '.join(operand_names)}), "
                    f"operators (+, -, *, /), parentheses, numeric literals."
                )

        # Validate parenthesis balance
        depth = 0
        for token in validated_tokens:
            if token == "(":
                depth += 1
            elif token == ")":
                depth -= 1
            if depth < 0:
                raise ValueError("Unmatched closing parenthesis in expression")
        if depth != 0:
            raise ValueError("Unmatched opening parenthesis in expression")

        # Verify all referenced operands exist
        used_operands = {t for t in re.findall(r"[a-zA-Z_]\w*", expression)}
        unknown = used_operands - set(operand_names)
        if unknown:
            raise ValueError(
                f"Unknown operand(s) in expression: {', '.join(unknown)}. "
                f"Defined operands: {', '.join(operand_names)}"
            )

        # Verify no unused operands
        unused = set(operand_names) - used_operands
        if unused:
            raise ValueError(
                f"Unused operand(s): {', '.join(unused)}. "
                f"All defined operands must appear in the expression. "
                f"Remove them or update the expression."
            )

        # Wrap division denominators with iff(x == 0, real(null), x)
        result_tokens = []
        i = 0
        while i < len(validated_tokens):
            if validated_tokens[i] == "/" and i + 1 < len(validated_tokens):
                next_token = validated_tokens[i + 1]
                result_tokens.append("/")

                if next_token.startswith("op_"):
                    result_tokens.append(f"iff(todouble({next_token}) == 0, real(null), todouble({next_token}))")
                    i += 2
                elif next_token == "(":
                    paren_depth = 0
                    sub_tokens = []
                    j = i + 1
                    while j < len(validated_tokens):
                        if validated_tokens[j] == "(":
                            paren_depth += 1
                        elif validated_tokens[j] == ")":
                            paren_depth -= 1
                        sub_tokens.append(validated_tokens[j])
                        if paren_depth == 0:
                            break
                        j += 1
                    inner = " ".join(sub_tokens[1:-1])
                    result_tokens.append(f"iff(todouble(( {inner} )) == 0, real(null), todouble(( {inner} )))")
                    i = j + 1
                else:
                    result_tokens.append(f"iff(todouble({next_token}) == 0, real(null), todouble({next_token}))")
                    i += 2
            else:
                result_tokens.append(validated_tokens[i])
                i += 1

        return " ".join(result_tokens)
