#!/usr/bin/env python3
"""Incremental drift backfill from ClickHouse to ADX, for a single org+app.

Constraints:
  * ClickHouse: SELECT-only. No INSERT/UPDATE/DELETE/ALTER/DROP/TRUNCATE.
  * ADX: additive. New rows only via .ingest inline. No DROP/ALTER/.delete.

Approach (per table):
  1. Get max(<watermark_col>) from ADX. That's the watermark.
  2. SELECT rows from CH where <watermark_col> > watermark.
  3. Inline-ingest into ADX in batches (size-capped so each .ingest inline
     command stays well under the cluster's per-command payload limit).
  4. Re-count both sides; report.

Idempotent: re-running is safe — the second pass finds 0 rows to move
because the watermark has advanced.

Usage:
  # Dry-run (default): just show what would be moved, no ADX writes.
  python scripts/backfill_ch_to_adx_incremental.py \
    --org fa7b153b-6998-416d-8adc-3e41c3971524 \
    --app 6fa6d19b-21e4-44be-8103-7ab1b5324eec

  # Actually backfill:
  python scripts/backfill_ch_to_adx_incremental.py \
    --org fa7b153b-6998-416d-8adc-3e41c3971524 \
    --app 6fa6d19b-21e4-44be-8103-7ab1b5324eec \
    --apply

Env:
  CH_HOST, CH_PORT, CH_USER, CH_PASSWORD — ClickHouse connection
  ADX_CLUSTER_URI                         — ADX cluster
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta

import clickhouse_connect
from azure.identity import DefaultAzureCredential
from azure.kusto.data import KustoClient, KustoConnectionStringBuilder
from azure.kusto.data.client_request_properties import ClientRequestProperties


# ── Config ──────────────────────────────────────────────────────────────────

CH_HOST = os.environ.get("CH_HOST", "136.111.66.222")
CH_PORT = int(os.environ.get("CH_PORT", "8123"))
CH_USER = os.environ.get("CH_USER", "default")
CH_PASSWORD = os.environ.get("CH_PASSWORD", "JVXCmZGjYybCAnqtOgVY")
ADX_CLUSTER = os.environ.get(
    "ADX_CLUSTER_URI", "https://kresadxdev.centralindia.kusto.windows.net"
)

# Each entry: (watermark column, ordered column list matching the ADX schema).
# business_metrics is intentionally absent — its counts already match and it
# uses ReplacingMergeTree with a composite key; re-ingest would be a no-op
# semantically but would add duplicate Kusto extents.
TABLES = {
    "raw_events": {
        "watermark": "server_ts",
        "cols": ["event_id", "user_id", "event_name", "event_data", "client_ts", "server_ts"],
    },
    "event_props": {
        "watermark": "server_ts",
        "cols": ["event_id", "user_id", "event_name", "key", "value", "client_ts", "server_ts"],
    },
    "user_profile_props": {
        "watermark": "server_ts",
        "cols": ["user_id", "key", "value", "server_ts"],
    },
    "user_experience": {
        "watermark": "assigned_at",
        "cols": [
            "user_id", "experience_id", "personalisation_id", "personalisation_name",
            "experience_variant_id", "features", "evaluation_reason", "assigned_at",
        ],
    },
}

# Inline ingest payload cap is ~1MB practical. 500 rows × ~500 bytes/row = ~250KB.
BATCH_SIZE = 500


# ── Helpers ─────────────────────────────────────────────────────────────────

def sanitize(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", s)


def db_name(org_id: str, app_id: str) -> str:
    return f"org_{sanitize(org_id)}_app_{sanitize(app_id)}"


def ch_client():
    return clickhouse_connect.get_client(
        host=CH_HOST, port=CH_PORT, username=CH_USER, password=CH_PASSWORD,
    )


def adx_client():
    kcsb = KustoConnectionStringBuilder.with_azure_token_credential(
        ADX_CLUSTER, DefaultAzureCredential(),
    )
    return KustoClient(kcsb)


def mgmt_props() -> ClientRequestProperties:
    props = ClientRequestProperties()
    props.set_option(
        ClientRequestProperties.request_timeout_option_name, timedelta(minutes=5),
    )
    return props


def adx_watermark(adx: KustoClient, db: str, table: str, col: str) -> datetime | None:
    """Return the max(col) in ADX, or None if table is empty."""
    r = adx.execute_query(db, f"{table} | summarize m = max({col})")
    row = list(r.primary_results[0])[0]
    return row["m"]


def adx_count(adx: KustoClient, db: str, table: str) -> int:
    r = adx.execute_query(db, f"{table} | count")
    return list(r.primary_results[0])[0]["Count"]


def ch_count(ch, db: str, table: str) -> int:
    return ch.query(f"SELECT count() FROM `{db}`.`{table}`").result_rows[0][0]


def ch_rows_after(ch, db: str, table: str, cols: list[str], wm_col: str, watermark: datetime | None):
    cols_csv = ", ".join(cols)
    if watermark is None:
        # ADX table empty — full copy.
        sql = f"SELECT {cols_csv} FROM `{db}`.`{table}`"
    else:
        iso = watermark.strftime("%Y-%m-%d %H:%M:%S.%f")
        sql = f"SELECT {cols_csv} FROM `{db}`.`{table}` WHERE `{wm_col}` > '{iso}'"
    r = ch.query(sql)
    if not r.result_rows:
        return []
    return [dict(zip(r.column_names, row)) for row in r.result_rows]


def _json_serial(v):
    """Convert a CH-returned value into something json.dumps + ADX can swallow."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, (dict, list)):
        return v
    return str(v) if not isinstance(v, (int, float, bool)) else v


def serialize_row(row: dict) -> dict:
    return {k: _json_serial(v) for k, v in row.items()}


def inline_ingest(adx: KustoClient, db: str, table: str, rows: list[dict]):
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        json_lines = "\n".join(json.dumps(serialize_row(r)) for r in batch)
        cmd = (
            f".ingest inline into table {table} "
            f"with (format='multijson') <|\n{json_lines}"
        )
        adx.execute_mgmt(db, cmd, mgmt_props())
        print(f"      batch {i // BATCH_SIZE + 1}: ingested {len(batch)} rows")


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--org", required=True, help="organisation UUID")
    ap.add_argument("--app", required=True, help="app UUID")
    ap.add_argument("--apply", action="store_true",
                    help="actually ingest. Without this flag, dry-run only.")
    args = ap.parse_args()

    db = db_name(args.org, args.app)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"\n  Mode:       {mode}")
    print(f"  Org:        {args.org}")
    print(f"  App:        {args.app}")
    print(f"  Database:   {db}")
    print(f"  CH:         {CH_HOST}:{CH_PORT} (SELECT-only)")
    print(f"  ADX:        {ADX_CLUSTER}")
    print()

    ch = ch_client()
    adx = adx_client()

    # Sanity: confirm both sides have the database.
    try:
        adx.execute_query(db, "print 1").primary_results[0]
    except Exception as e:
        print(f"  ABORT: ADX db {db} not accessible: {str(e)[:200]}", file=sys.stderr)
        sys.exit(1)

    ch_dbs = [r[0] for r in ch.query("SHOW DATABASES").result_rows]
    if db not in ch_dbs:
        print(f"  ABORT: CH db {db} does not exist", file=sys.stderr)
        sys.exit(1)

    grand_planned = 0
    grand_ingested = 0

    for table, spec in TABLES.items():
        wm_col = spec["watermark"]
        cols = spec["cols"]
        print(f"  {table}:")
        ch_n = ch_count(ch, db, table)
        adx_n_before = adx_count(adx, db, table)
        print(f"      CH={ch_n}  ADX={adx_n_before}  delta={ch_n - adx_n_before}")

        watermark = adx_watermark(adx, db, table, wm_col)
        print(f"      ADX watermark ({wm_col}): {watermark}")

        rows = ch_rows_after(ch, db, table, cols, wm_col, watermark)
        print(f"      CH rows newer than watermark: {len(rows)}")
        grand_planned += len(rows)

        if not rows:
            print(f"      nothing to do")
            print()
            continue

        if not args.apply:
            print(f"      (dry-run; not ingesting)")
            print()
            continue

        inline_ingest(adx, db, table, rows)
        grand_ingested += len(rows)

        adx_n_after = adx_count(adx, db, table)
        print(f"      ADX after:  {adx_n_after}  (delta-after={ch_n - adx_n_after})")
        print()

    print(f"  TOTALS:  planned={grand_planned}  ingested={grand_ingested}")
    if not args.apply:
        print(f"\n  This was a dry-run. Re-run with --apply to ingest.")


if __name__ == "__main__":
    main()
