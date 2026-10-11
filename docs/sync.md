### Sync Export API (/api/v1/sync)

Read-only export of an app's ClickHouse analytics tables, so another service can keep an exact
copy. The caller pulls new rows by cursor and periodically compares per-day digests to find
rows that were deleted or re-keyed at the source.

Common requirements:

- Bearer token (JWT) with app context. SDK keys are refused.
- Organisation and app always come from the token.

Exported tables: `raw_events`, `event_props`, `user_profile_props`, `user_experience`,
`business_metrics`. Any other name returns 404.

---

## How the export orders rows

Every analytics row has two columns filled by ClickHouse at insert:

| Column | Meaning |
|---|---|
| `_written_at` | When the row was written (UTC, microseconds). Not the event time. |
| `_row_id` | Unique id of that written row. |

Rows are exported in `(_written_at, _row_id)` order. This is why late or backdated events are
never skipped: a row's position depends on when it was written, not on `client_ts`.

Things a caller must know:

- **Identity merges create new rows.** `/users/identify/` copies the anonymous user's rows
  under the identified `user_id` and deletes the originals. The copies get a new `_row_id`
  and `_written_at`, so a pull delivers them; the deleted originals are only found by
  comparing digests.
- **The newest rows are withheld** for `SYNC_WATERMARK_LAG_SECONDS` (default 30). Each
  response carries the `watermark` it was computed at.
- **`business_metrics` is exported deduplicated**: only the current row for each
  `(metric_name, dimension, period_start, scenario_id)`. Use that key, not `_row_id`, as its
  identity in a copy.
- **Timestamps are UTC strings** in ClickHouse's format (`2026-10-11 12:00:00.000`), returned
  exactly as stored.

---

#### GET /api/v1/sync/tables/

Row count and newest write time per table, up to the watermark.

```json
{
  "watermark": "2026-10-11 12:00:00.000000",
  "tables": [
    {"name": "raw_events", "row_count": 32620, "max_written_at": "2026-10-11 11:59:12.403118"},
    {"name": "business_metrics", "row_count": 0, "max_written_at": null}
  ]
}
```

---

#### GET /api/v1/sync/{table}/rows/

A page of rows after the cursor.

| Query parameter | Notes |
|---|---|
| `limit` | 1 to `SYNC_EXPORT_MAX_LIMIT` (default page 5000, maximum 10000). |
| `after_ts`, `after_id` | The cursor. Both or neither. Use the `next_cursor` of the previous page unchanged. |
| `day` | `YYYY-MM-DD`. Only rows written on that UTC day. Used to reload one day. |
| `until` | Upper bound on `_written_at`. Can only lower the watermark, never raise it. |

```json
{
  "rows": [
    {
      "event_id": "0b2f…", "user_id": "u_17", "event_name": "match_joined",
      "event_data": "{\"mode\":\"squad\"}",
      "client_ts": "2026-10-11 11:58:40.120", "server_ts": "2026-10-11 11:58:41.002",
      "_row_id": "3cc3f7f1-6075-414b-8975-bbdb2dbba6fa",
      "_written_at": "2026-10-11 11:58:41.019334",
      "_row_hash": "8694985181137147129"
    }
  ],
  "next_cursor": {"after_ts": "2026-10-11 11:58:41.019334", "after_id": "3cc3f7f1-6075-414b-8975-bbdb2dbba6fa"},
  "has_more": false,
  "watermark": "2026-10-11 12:00:00.000000"
}
```

- `next_cursor` is `null` when the page is empty: keep the cursor you already have.
- Save the cursor in the same transaction as the rows. Replaying a page is then harmless.
- `_row_hash` is a 64-bit hash of the row's data columns, as a decimal string.

---

#### GET /api/v1/sync/{table}/digest/

Row count and checksum per UTC day of write time.

| Query parameter | Notes |
|---|---|
| `from`, `to` | `YYYY-MM-DD`, inclusive. Omit for every day. |
| `until` | As above. |

```json
{
  "days": [{"day": "2026-10-10", "row_count": 4812, "checksum": "15939996377549152164"}],
  "watermark": "2026-10-11 12:00:00.000000"
}
```

`checksum` is the sum of the day's `_row_hash` values modulo 2^64. To compare a copy: sum the
stored hashes of its rows with `_written_at <= watermark`, grouped by the date part of
`_written_at`, modulo 2^64. A day whose count or checksum differs is replaced by deleting it
and reloading it with `rows/?day=…&until=<the same watermark>`.

---

## Errors

| Status | When |
|---|---|
| 401 / 403 | Missing, invalid or SDK token; token without app context. |
| 404 | Table name not in the exported list. |
| 422 | `limit` out of range, half a cursor, malformed timestamp, UUID or date, `from` after `to`. |
| 503 | ClickHouse unreachable, or the table predates the marker columns and the migration has not run. |

An app that has tracked nothing returns empty results, not an error.

---

## Operations

- `scripts/bootstrap_clickhouse.py` adds the marker columns to tables created before they
  existed and stores values for their existing rows. It is idempotent and runs on every
  deploy. Existing rows all receive the time of that run as `_written_at`.
- `scripts/verify_sync_api.py` proves the export end to end against a running environment.
- Do not delete data from ClickHouse while a copy is behind: rows it has not yet pulled would
  be gone from both sides.
