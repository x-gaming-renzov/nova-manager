from nova_manager.components.sync.tables import SyncTable

# Every request value is bound as a server-side parameter. Only the table (from the fixed
# catalogue) and the database (derived from the caller's token) are written into the SQL.

_UNTIL = "parseDateTime64BestEffort({until:String}, 6, 'UTC')"
_DAY = "toDate(_written_at, 'UTC')"


def _utc_string(expression: str) -> str:
    return f"toString(toTimeZone({expression}, 'UTC'))"


def _source(table: SyncTable, database_name: str) -> str:
    return f"{database_name}.{table.name}" + (" FINAL" if table.final else "")


def _row_hash(table: SyncTable) -> str:
    return f"cityHash64({', '.join(table.columns)})"


def build_watermark_query(lag_seconds: int, until: str | None = None) -> tuple[str, dict]:
    """Newest write time the export will show.

    An insert still in flight can carry a write time older than rows already visible, so the
    last few seconds are withheld. A caller may ask for an earlier limit, never a later one.
    """
    limit = "subtractSeconds(now64(6), {lag:UInt32})"
    params: dict = {"lag": lag_seconds}
    if until is not None:
        limit = f"least({limit}, {_UNTIL})"
        params["until"] = until
    return f"SELECT {_utc_string(limit)} AS watermark", params


def build_rows_query(
    table: SyncTable,
    database_name: str,
    until: str,
    limit: int,
    after_ts: str | None = None,
    after_id: str | None = None,
    day: str | None = None,
) -> tuple[str, dict]:
    columns = [
        f"{_utc_string(column)} AS {column}" if column in table.datetime_columns else column
        for column in table.columns
    ]
    where = [f"_written_at <= {_UNTIL}"]
    # One row beyond the page tells the caller whether another page exists.
    params: dict = {"until": until, "limit": limit + 1}
    if after_ts is not None and after_id is not None:
        # The plain bound is redundant for correctness but is what lets the minmax index skip
        # parts older than the cursor; ClickHouse does not use it for the tuple comparison.
        where.append("_written_at >= parseDateTime64BestEffort({after_ts:String}, 6, 'UTC')")
        where.append(
            "(_written_at, _row_id) > "
            "(parseDateTime64BestEffort({after_ts:String}, 6, 'UTC'), toUUID({after_id:String}))"
        )
        params["after_ts"] = after_ts
        params["after_id"] = after_id
    if day is not None:
        where.append(f"{_DAY} = toDate({{day:String}})")
        params["day"] = day

    # prefer_column_name_to_alias: the datetime columns are re-aliased as strings under their
    # own names; the hash and the filters must still see the stored column, as the digest does.
    sql = f"""
        SELECT
            {", ".join(columns)},
            toString(_row_id) AS _row_id,
            {_utc_string("_written_at")} AS _written_at,
            toString({_row_hash(table)}) AS _row_hash
        FROM {_source(table, database_name)}
        WHERE {" AND ".join(where)}
        ORDER BY _written_at, _row_id
        LIMIT {{limit:UInt32}}
        SETTINGS prefer_column_name_to_alias = 1
    """
    return sql, params


def build_digest_query(
    table: SyncTable,
    database_name: str,
    until: str,
    from_day: str | None = None,
    to_day: str | None = None,
) -> tuple[str, dict]:
    where = [f"_written_at <= {_UNTIL}"]
    params: dict = {"until": until}
    if from_day is not None:
        where.append(f"{_DAY} >= toDate({{from_day:String}})")
        params["from_day"] = from_day
    if to_day is not None:
        where.append(f"{_DAY} <= toDate({{to_day:String}})")
        params["to_day"] = to_day

    # sum() over UInt64 wraps modulo 2^64; the mirror sums the per-row hashes the same way.
    sql = f"""
        SELECT
            toString({_DAY}) AS day,
            count() AS row_count,
            toString(sum({_row_hash(table)})) AS checksum
        FROM {_source(table, database_name)}
        WHERE {" AND ".join(where)}
        GROUP BY day
        ORDER BY day
    """
    return sql, params


def build_summary_query(table: SyncTable, database_name: str, until: str) -> tuple[str, dict]:
    sql = f"""
        SELECT
            count() AS row_count,
            {_utc_string("max(_written_at)")} AS max_written_at
        FROM {_source(table, database_name)}
        WHERE _written_at <= {_UNTIL}
    """
    return sql, {"until": until}
