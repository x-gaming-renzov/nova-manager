from dataclasses import dataclass


@dataclass(frozen=True)
class SyncTable:
    name: str
    # Data columns in table order. The row hash is taken over exactly these, in this order.
    columns: tuple[str, ...]
    datetime_columns: tuple[str, ...]
    # ReplacingMergeTree keeps superseded rows until a merge; FINAL exports only the live one.
    final: bool = False


SYNC_TABLES: dict[str, SyncTable] = {
    table.name: table
    for table in (
        SyncTable(
            name="raw_events",
            columns=("event_id", "user_id", "event_name", "event_data", "client_ts", "server_ts"),
            datetime_columns=("client_ts", "server_ts"),
        ),
        SyncTable(
            name="event_props",
            columns=("event_id", "user_id", "event_name", "key", "value", "client_ts", "server_ts"),
            datetime_columns=("client_ts", "server_ts"),
        ),
        SyncTable(
            name="user_profile_props",
            columns=("user_id", "key", "value", "server_ts"),
            datetime_columns=("server_ts",),
        ),
        SyncTable(
            name="user_experience",
            columns=(
                "user_id",
                "experience_id",
                "personalisation_id",
                "personalisation_name",
                "experience_variant_id",
                "features",
                "evaluation_reason",
                "assigned_at",
            ),
            datetime_columns=("assigned_at",),
        ),
        SyncTable(
            name="business_metrics",
            columns=(
                "metric_name",
                "dimension",
                "value",
                "currency",
                "scenario_id",
                "period_start",
                "created_at",
            ),
            datetime_columns=("period_start", "created_at"),
            final=True,
        ),
    )
}
