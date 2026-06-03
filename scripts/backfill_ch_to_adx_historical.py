#!/usr/bin/env python3
"""Historical gap backfill from ClickHouse to ADX.

Sibling to backfill_ch_to_adx_incremental.py (which handles drift — rows
newer than the ADX watermark). This one handles the orthogonal case:
rows whose timestamp falls INSIDE the existing ADX range but whose
identifiers aren't present.

For Batlin, this is the chunk of events that hit CH between the May 17
migration and the ADX cutover (~June 1-2) — when writes were CH-only.

Constraints (same as the incremental script):
  * ClickHouse: SELECT-only.
  * ADX: additive only. No DROP, no .delete, no .alter.

Approach (per table):
  1. Load all primary keys from ADX into a Python set.
  2. Stream rows from CH; for each, check if the PK is in the ADX set.
  3. Batch the missing rows into .ingest inline commands.
  4. Re-count and report.

Primary keys:
  raw_events, event_props  → event_id (string UUID)
  user_profile_props       → composite (user_id, key, server_ts)
  user_experience          → composite (user_id, experience_id, assigned_at)

Usage:
  python scripts/backfill_ch_to_adx_historical.py \
    --org fa7b153b-6998-416d-8adc-3e41c3971524 \
    --app 6fa6d19b-21e4-44be-8103-7ab1b5324eec               # dry-run

  python scripts/backfill_ch_to_adx_historical.py \
    --org fa7b153b-6998-416d-8adc-3e41c3971524 \
    --app 6fa6d19b-21e4-44be-8103-7ab1b5324eec --apply       # actually ingest
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


CH_HOST = os.environ.get("CH_HOST", "136.111.66.222")
CH_PORT = int(os.environ.get("CH_PORT", "8123"))
CH_USER = os.environ.get("CH_USER", "default")
CH_PASSWORD = os.environ.get("CH_PASSWORD", "JVXCmZGjYybCAnqtOgVY")
ADX_CLUSTER = os.environ.get(
    "ADX_CLUSTER_URI", "https://kresadxdev.centralindia.kusto.windows.net"
)

# Each table: which columns identify a row, plus the full column list.
# pk_cols is what we project into both ADX and CH to build the "is this row
# already there?" set. cols is the full set to copy.
TABLES = {
    "raw_events": {
        "pk_cols": ["event_id"],
        "cols": ["event_id", "user_id", "event_name", "event_data", "client_ts", "server_ts"],
    },
    "event_props": {
        "pk_cols": ["event_id", "key"],  # event_props has multiple props per event_id
        "cols": ["event_id", "user_id", "event_name", "key", "value", "client_ts", "server_ts"],
    },
    "user_profile_props": {
        "pk_cols": ["user_id", "key", "server_ts"],
        "cols": ["user_id", "key", "value", "server_ts"],
    },
}

BATCH_SIZE = 500


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
    p = ClientRequestProperties()
    p.set_option(ClientRequestProperties.request_timeout_option_name, timedelta(minutes=5))
    return p


def query_props() -> ClientRequestProperties:
    p = ClientRequestProperties()
    p.set_option(ClientRequestProperties.request_timeout_option_name, timedelta(minutes=2))
    return p


def _key_of(row: dict, pk_cols: list[str]) -> tuple:
    """Hashable composite key. Normalize datetimes to ISO strings so the
    same instant compared across CH/ADX matches."""
    out = []
    for c in pk_cols:
        v = row[c]
        if isinstance(v, datetime):
            # Strip tz info to compare CH (naive) vs ADX (aware) consistently.
            v = v.replace(tzinfo=None).isoformat(timespec="microseconds")
        out.append(v)
    return tuple(out)


def adx_keys(adx: KustoClient, db: str, table: str, pk_cols: list[str]) -> set[tuple]:
    """Project pk_cols from ADX into a Python set."""
    project = ", ".join(pk_cols)
    q = f"{table} | project {project}"
    r = adx.execute_query(db, q, query_props())
    primary = r.primary_results[0]
    cols = [c.column_name for c in primary.columns]
    keys = set()
    for row in primary:
        d = {c: row[c] for c in cols}
        keys.add(_key_of(d, pk_cols))
    return keys


def ch_all_rows(ch, db: str, table: str, cols: list[str]):
    sql = f"SELECT {', '.join(cols)} FROM `{db}`.`{table}`"
    r = ch.query(sql)
    if not r.result_rows:
        return []
    return [dict(zip(r.column_names, row)) for row in r.result_rows]


def adx_count(adx: KustoClient, db: str, table: str) -> int:
    r = adx.execute_query(db, f"{table} | count", query_props())
    return list(r.primary_results[0])[0]["Count"]


def ch_count(ch, db: str, table: str) -> int:
    return ch.query(f"SELECT count() FROM `{db}`.`{table}`").result_rows[0][0]


def _json_serial(v):
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
        cmd = f".ingest inline into table {table} with (format='multijson') <|\n{json_lines}"
        adx.execute_mgmt(db, cmd, mgmt_props())
        print(f"      batch {i // BATCH_SIZE + 1}: ingested {len(batch)} rows")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--org", required=True)
    ap.add_argument("--app", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--tables", nargs="+", help="restrict to specific tables")
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

    tables = args.tables if args.tables else list(TABLES.keys())
    grand_planned = 0
    grand_ingested = 0

    for table in tables:
        spec = TABLES[table]
        pk_cols = spec["pk_cols"]
        cols = spec["cols"]

        ch_n = ch_count(ch, db, table)
        adx_n_before = adx_count(adx, db, table)
        print(f"  {table}:")
        print(f"      CH={ch_n}  ADX={adx_n_before}  delta={ch_n - adx_n_before}")
        print(f"      pk_cols={pk_cols}")

        print(f"      Loading ADX keys...", flush=True)
        adx_pks = adx_keys(adx, db, table, pk_cols)
        print(f"      ADX has {len(adx_pks)} distinct keys")

        print(f"      Loading CH rows...", flush=True)
        ch_rows = ch_all_rows(ch, db, table, cols)
        print(f"      CH has {len(ch_rows)} rows")

        missing = [r for r in ch_rows if _key_of(r, pk_cols) not in adx_pks]
        print(f"      Missing in ADX: {len(missing)}")
        grand_planned += len(missing)

        if not missing:
            print()
            continue

        if not args.apply:
            print(f"      (dry-run; not ingesting)")
            print()
            continue

        inline_ingest(adx, db, table, missing)
        grand_ingested += len(missing)
        adx_n_after = adx_count(adx, db, table)
        print(f"      ADX after:  {adx_n_after}  (was {adx_n_before}, +{adx_n_after - adx_n_before})")
        print()

    print(f"  TOTALS:  planned={grand_planned}  ingested={grand_ingested}")
    if not args.apply:
        print(f"\n  This was a dry-run. Re-run with --apply to ingest.")


if __name__ == "__main__":
    main()
