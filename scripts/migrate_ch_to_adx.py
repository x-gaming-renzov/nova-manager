#!/usr/bin/env python3
"""
Migrate a ClickHouse org/app database to Azure Data Explorer.

Three phases:
  1. Export: ClickHouse → local JSON files (safe, no ADX needed)
  2. Ingest: JSON files → ADX via queued blob ingestion (reliable)
  3. Verify: Row counts + sample data + metric query comparison

Usage:
  # Migrate a specific app (all 3 phases):
  python scripts/migrate_ch_to_adx.py --org <org_id> --app <app_id>

  # Migrate all apps from Postgres:
  python scripts/migrate_ch_to_adx.py --all

  # Individual phases:
  python scripts/migrate_ch_to_adx.py --org <org_id> --app <app_id> --export-only
  python scripts/migrate_ch_to_adx.py --org <org_id> --app <app_id> --ingest-only
  python scripts/migrate_ch_to_adx.py --org <org_id> --app <app_id> --verify-only

  # Re-ingest specific tables:
  python scripts/migrate_ch_to_adx.py --org <org_id> --app <app_id> --ingest-only --tables raw_events user_experience

Env vars:
  CH_HOST          ClickHouse host (default: from GCP nova-data VM)
  CH_PORT          ClickHouse port (default: 8123)
  CH_USER          ClickHouse user (default: default)
  CH_PASSWORD      ClickHouse password (or from GCP secrets)
  ADX_CLUSTER_URI  ADX cluster URI
  ADX_RG           ADX resource group (default: KR-ESports-RG-Dev)
"""
import os
import re
import sys
import json
import time
import subprocess
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

TABLES = {
    "raw_events": {
        "columns": ["event_id", "user_id", "event_name", "event_data", "client_ts", "server_ts"],
        "adx_schema": "(event_id: string, user_id: string, event_name: string, event_data: dynamic, client_ts: datetime, server_ts: datetime)",
        "final": False,
    },
    "event_props": {
        "columns": ["event_id", "user_id", "event_name", "key", "value", "client_ts", "server_ts"],
        "adx_schema": "(event_id: string, user_id: string, event_name: string, key: string, value: string, client_ts: datetime, server_ts: datetime)",
        "final": False,
    },
    "user_profile_props": {
        "columns": ["user_id", "key", "value", "server_ts"],
        "adx_schema": "(user_id: string, key: string, value: string, server_ts: datetime)",
        "final": False,
    },
    "user_experience": {
        "columns": ["user_id", "experience_id", "personalisation_id", "personalisation_name", "experience_variant_id", "features", "evaluation_reason", "assigned_at"],
        "adx_schema": "(user_id: string, experience_id: string, personalisation_id: string, personalisation_name: string, experience_variant_id: string, features: dynamic, evaluation_reason: string, assigned_at: datetime)",
        "final": False,
    },
    "business_metrics": {
        "columns": ["metric_name", "dimension", "value", "currency", "scenario_id", "period_start", "created_at"],
        "adx_schema": "(metric_name: string, dimension: string, value: real, currency: string, scenario_id: string, period_start: datetime, created_at: datetime)",
        "final": True,
    },
}


def sanitize(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", s)


def db_name(org_id: str, app_id: str) -> str:
    return f"org_{sanitize(org_id)}_app_{sanitize(app_id)}"


def get_ch_client():
    import clickhouse_connect
    return clickhouse_connect.get_client(
        host=os.environ.get("CH_HOST", "136.111.66.222"),
        port=int(os.environ.get("CH_PORT", "8123")),
        username=os.environ.get("CH_USER", "default"),
        password=os.environ.get("CH_PASSWORD", "JVXCmZGjYybCAnqtOgVY"),
    )


def get_adx_clients():
    from azure.kusto.data import KustoClient, KustoConnectionStringBuilder
    from azure.kusto.ingest import QueuedIngestClient
    from azure.identity import DefaultAzureCredential

    cluster = os.environ.get("ADX_CLUSTER_URI", "https://kresadxdev.centralindia.kusto.windows.net")
    credential = DefaultAzureCredential()

    query_kcsb = KustoConnectionStringBuilder.with_azure_token_credential(cluster, credential)
    ingest_kcsb = KustoConnectionStringBuilder.with_azure_token_credential(cluster, credential)

    return KustoClient(query_kcsb), QueuedIngestClient(ingest_kcsb)


# ── Phase 1: Export ─────────────────────────────────────────

def export(org_id: str, app_id: str):
    ch = get_ch_client()
    db = db_name(org_id, app_id)
    export_dir = os.path.join(SCRIPT_DIR, "migration_data", db)
    os.makedirs(export_dir, exist_ok=True)

    print(f"\n  Database: {db}")

    # Check if DB exists in ClickHouse
    dbs = [r[0] for r in ch.query("SHOW DATABASES").result_rows]
    if db not in dbs:
        print(f"  SKIP — database does not exist in ClickHouse")
        return None

    exported = {}
    for tbl, cfg in TABLES.items():
        # Check if table exists
        ch_tables = [r[0] for r in ch.query(f"SHOW TABLES FROM `{db}`").result_rows]
        if tbl not in ch_tables:
            print(f"  {tbl}: SKIP (not in CH)")
            continue

        cols = ",".join(cfg["columns"])
        final = " FINAL" if cfg["final"] else ""
        result = ch.query(f"SELECT {cols} FROM `{db}`.`{tbl}`{final}")
        rows = result.result_rows
        col_names = result.column_names

        path = os.path.join(export_dir, f"{tbl}.jsonl")
        with open(path, "w") as f:
            for row in rows:
                d = {}
                for i, col in enumerate(col_names):
                    val = row[i]
                    if val is None:
                        d[col] = ""
                    elif isinstance(val, (dict, list)):
                        d[col] = val
                    else:
                        d[col] = str(val)
                f.write(json.dumps(d) + "\n")

        size_mb = os.path.getsize(path) / 1024 / 1024
        exported[tbl] = len(rows)
        print(f"  {tbl}: {len(rows)} rows ({size_mb:.1f} MB)")

    return exported


# ── Phase 2: Ingest ─────────────────────────────────────────

def ingest(org_id: str, app_id: str, tables_filter=None):
    from azure.kusto.ingest.ingestion_properties import IngestionProperties, DataFormat

    db = db_name(org_id, app_id)
    export_dir = os.path.join(SCRIPT_DIR, "migration_data", db)
    cluster = os.environ.get("ADX_CLUSTER_URI", "https://kresadxdev.centralindia.kusto.windows.net")
    rg = os.environ.get("ADX_RG", "KR-ESports-RG-Dev")
    cluster_name = cluster.split("//")[1].split(".")[0]

    query_client, ingest_client = get_adx_clients()

    # Create ADX database via ARM if needed
    print(f"\n  Database: {db}")
    result = subprocess.run(
        ["az", "kusto", "database", "create",
         "--cluster-name", cluster_name,
         "--resource-group", rg,
         "--database-name", db,
         "--read-write-database", "soft-delete-period=P365D", "hot-cache-period=P31D", "location=Central India"],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode == 0:
        print(f"  ADX database created")
    elif "already exists" in result.stderr.lower() or "conflict" in result.stderr.lower():
        print(f"  ADX database exists")
    else:
        print(f"  WARNING: DB create returned {result.returncode}: {result.stderr[:100]}")

    targets = tables_filter or list(TABLES.keys())
    ingested = {}

    for tbl in targets:
        cfg = TABLES[tbl]
        path = os.path.join(export_dir, f"{tbl}.jsonl")

        if not os.path.exists(path):
            print(f"  {tbl}: SKIP (no export file at {path})")
            continue

        row_count = sum(1 for _ in open(path))
        print(f"  {tbl}: {row_count} rows", flush=True)

        # Drop and recreate
        for attempt in range(3):
            try:
                query_client.execute_mgmt(db, f".drop table {tbl} ifexists")
                query_client.execute_mgmt(db, f".create table {tbl} {cfg['adx_schema']}")
                print(f"    Table recreated", flush=True)
                break
            except Exception as e:
                print(f"    DDL attempt {attempt+1} failed: {str(e)[:60]}", flush=True)
                time.sleep(5 * (attempt + 1))
        else:
            print(f"    FAILED to create table — skipping")
            continue

        # Queued blob ingestion (reliable)
        for attempt in range(3):
            try:
                props = IngestionProperties(database=db, table=tbl, data_format=DataFormat.MULTIJSON)
                ingest_client.ingest_from_file(path, ingestion_properties=props)
                print(f"    Queued (attempt {attempt+1})", flush=True)
                ingested[tbl] = row_count
                break
            except Exception as e:
                print(f"    Ingest attempt {attempt+1} failed: {str(e)[:80]}", flush=True)
                time.sleep(10 * (attempt + 1))
        else:
            print(f"    FAILED to queue ingestion")

    print(f"\n  Queued {len(ingested)} tables. ADX processes within ~5 minutes.")
    print(f"  Then run: python scripts/migrate_ch_to_adx.py --org {org_id} --app {app_id} --verify-only")
    return ingested


# ── Phase 3: Verify ─────────────────────────────────────────

def verify(org_id: str, app_id: str):
    from nova_manager.components.metrics.query_builder import QueryBuilder
    from nova_manager.components.metrics.kql_query_builder import KQLQueryBuilder

    ch = get_ch_client()
    query_client, _ = get_adx_clients()
    db = db_name(org_id, app_id)
    export_dir = os.path.join(SCRIPT_DIR, "migration_data", db)

    PASS = 0
    FAIL = 0

    def check(label, cond, detail=""):
        nonlocal PASS, FAIL
        if cond:
            print(f"  PASS  {label}")
            PASS += 1
        else:
            print(f"  FAIL  {label}  {detail}")
            FAIL += 1

    def adx_query(kql):
        r = query_client.execute_query(db, kql)
        cols = [c.column_name for c in r.primary_results[0].columns]
        return [{c: row[c] for c in cols} for row in r.primary_results[0]]

    def ch_query(sql):
        r = ch.query(sql)
        return [dict(zip(r.column_names, row)) for row in r.result_rows] if r.result_rows else []

    # ── Level 1: Row counts ──
    print(f"\n{'='*60}")
    print(f"  LEVEL 1: ROW COUNTS")
    print(f"{'='*60}")

    for tbl in TABLES:
        # Compare against export file (ground truth) not live CH (which may have grown)
        export_path = os.path.join(export_dir, f"{tbl}.jsonl")
        if os.path.exists(export_path):
            export_cnt = sum(1 for _ in open(export_path))
        else:
            export_cnt = ch.query(f"SELECT count() FROM `{db}`.`{tbl}`").result_rows[0][0]

        try:
            adx_cnt = adx_query(f"{tbl} | count")[0]["Count"]
        except Exception:
            adx_cnt = 0

        check(f"{tbl}: export={export_cnt} ADX={adx_cnt}", export_cnt == adx_cnt)

    # ── Level 2: Sample data ──
    print(f"\n{'='*60}")
    print(f"  LEVEL 2: SAMPLE DATA")
    print(f"{'='*60}")

    try:
        ch_s = ch_query(f"SELECT event_id, user_id, event_name FROM `{db}`.raw_events ORDER BY event_id LIMIT 5")
        adx_s = adx_query("raw_events | project event_id, user_id, event_name | order by event_id asc | take 5")
        for i, (c, a) in enumerate(zip(ch_s, adx_s)):
            match = c["event_id"] == a["event_id"] and c["user_id"] == a["user_id"]
            check(f"raw_events[{i}]: {c['event_id'][:12]}...", match)
    except Exception as e:
        check(f"raw_events sample", False, str(e)[:60])

    try:
        ch_s = ch_query(f"SELECT user_id, key, value FROM `{db}`.user_profile_props ORDER BY user_id, key LIMIT 5")
        adx_s = adx_query("user_profile_props | project user_id, key, value | order by user_id asc, key asc | take 5")
        for i, (c, a) in enumerate(zip(ch_s, adx_s)):
            match = c["user_id"] == a["user_id"] and c["key"] == a["key"] and c["value"] == a["value"]
            check(f"user_profile_props[{i}]: {c['user_id'][:8]}../{c['key']}", match)
    except Exception as e:
        check(f"user_profile_props sample", False, str(e)[:60])

    # ── Level 3: Metric queries (CH SQL vs KQL) ──
    print(f"\n{'='*60}")
    print(f"  LEVEL 3: METRIC QUERIES (same query, both backends)")
    print(f"{'='*60}")

    ch_qb = QueryBuilder(org_id, app_id)
    adx_qb = KQLQueryBuilder(org_id, app_id)

    # Find data time range
    try:
        ch_range = ch_query(f"SELECT min(client_ts) as mn, max(client_ts) as mx FROM `{db}`.raw_events")
        if ch_range and ch_range[0]["mn"]:
            # Use a fixed cutoff before export to avoid drift
            TR = {"start": str(ch_range[0]["mn"])[:19], "end": "2026-05-15 00:00:00"}

            top = ch_query(f"SELECT event_name, count() as cnt FROM `{db}`.raw_events WHERE client_ts < '2026-05-15' GROUP BY event_name ORDER BY cnt DESC LIMIT 3")

            for evt_row in top[:2]:
                evt = evt_row["event_name"]

                # Count
                ch_r = ch_query(ch_qb.build_query("count", {"event_name": evt, "distinct": False, "time_range": TR, "granularity": "monthly", "group_by": [], "filters": {}}))
                adx_r = adx_query(adx_qb.build_query("count", {"event_name": evt, "distinct": False, "time_range": TR, "granularity": "monthly", "group_by": [], "filters": {}}))
                ch_t = sum(r["value"] for r in ch_r)
                adx_t = sum(r["value"] for r in adx_r)
                check(f"count({evt}): CH={ch_t} ADX={adx_t}", ch_t == adx_t)

                # Distinct
                ch_r = ch_query(ch_qb.build_query("count", {"event_name": evt, "distinct": True, "time_range": TR, "granularity": "monthly", "group_by": [], "filters": {}}))
                adx_r = adx_query(adx_qb.build_query("count", {"event_name": evt, "distinct": True, "time_range": TR, "granularity": "monthly", "group_by": [], "filters": {}}))
                ch_t = sum(r["value"] for r in ch_r)
                adx_t = sum(r["value"] for r in adx_r)
                check(f"dcount({evt}): CH={ch_t} ADX={adx_t}", ch_t == adx_t)

            # Business metrics
            BM_TR = {"start": "2026-01-01 00:00:00", "end": "2027-01-01 00:00:00"}
            bm_names = ch_query(f"SELECT DISTINCT metric_name FROM `{db}`.business_metrics FINAL LIMIT 5")
            for bm in bm_names[:3]:
                mn = bm["metric_name"]
                ch_r = ch_query(ch_qb.build_query("operational", {"metric_name": mn, "aggregation": "sum", "time_range": BM_TR, "granularity": "monthly", "group_by": [], "filters": {}}))
                adx_r = adx_query(adx_qb.build_query("operational", {"metric_name": mn, "aggregation": "sum", "time_range": BM_TR, "granularity": "monthly", "group_by": [], "filters": {}}))
                ch_vals = {str(r["period"])[:7]: r["value"] for r in ch_r}
                adx_vals = {str(r["period"])[:7]: r["value"] for r in adx_r}
                match = all(
                    abs(ch_vals.get(m, 0) - adx_vals.get(m, 0)) / abs(ch_vals[m]) < 0.01
                    for m in ch_vals if ch_vals[m] != 0
                )
                check(f"operational({mn})", match)
        else:
            print("  No event data — skipping metric queries")
    except Exception as e:
        check(f"metric queries", False, str(e)[:80])

    # ── Summary ──
    print(f"\n{'='*60}")
    print(f"  {db}")
    print(f"  RESULT: {PASS} passed, {FAIL} failed")
    print(f"{'='*60}")
    return FAIL == 0


# ── Main ────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate ClickHouse → ADX")
    parser.add_argument("--org", help="Organisation ID")
    parser.add_argument("--app", help="App ID")
    parser.add_argument("--all", action="store_true", help="Migrate all apps from Postgres")
    parser.add_argument("--export-only", action="store_true")
    parser.add_argument("--ingest-only", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--tables", nargs="+", help="Only ingest these tables")
    args = parser.parse_args()

    if args.all:
        from nova_manager.database.session import SessionLocal
        from sqlalchemy import text
        db_session = SessionLocal()
        apps = db_session.execute(text("SELECT organisation_id, pid, name FROM apps")).fetchall()
        db_session.close()
        pairs = [(str(r[0]), str(r[1]), r[2]) for r in apps]
    elif args.org and args.app:
        pairs = [(args.org, args.app, "")]
    else:
        parser.error("Provide --org and --app, or use --all")

    for org_id, app_id, name in pairs:
        label = f"{name} ({org_id[:8]}.../{app_id[:8]}...)" if name else f"{org_id}/{app_id}"
        print(f"\n{'#'*60}")
        print(f"  {label}")
        print(f"{'#'*60}")

        if args.verify_only:
            verify(org_id, app_id)
        elif args.export_only:
            export(org_id, app_id)
        elif args.ingest_only:
            ingest(org_id, app_id, args.tables)
        else:
            exported = export(org_id, app_id)
            if exported:
                ingest(org_id, app_id, args.tables)
                print(f"\n  ⏳ Wait ~5 minutes for ADX to process, then verify:")
                print(f"  python scripts/migrate_ch_to_adx.py --org {org_id} --app {app_id} --verify-only")
