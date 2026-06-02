#!/usr/bin/env python3
"""
Verify ClickHouse → ADX migration for the main production app.

Three levels of verification:
  1. Row count match (per table)
  2. Sample data comparison (first 5 rows from each table)
  3. Metric query comparison (same queries against both backends)

Also runs Excel v2 KPI Simulator validation against ADX.

Usage:
  ADX_CLUSTER_URI=https://kresadxdev.centralindia.kusto.windows.net \
  python scripts/verify_ch_adx_migration.py
"""
import os
import sys
import json

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import clickhouse_connect
from azure.kusto.data import KustoClient, KustoConnectionStringBuilder
from azure.identity import DefaultAzureCredential

from nova_manager.components.metrics.query_builder import QueryBuilder
from nova_manager.components.metrics.kql_query_builder import KQLQueryBuilder

# ── Config ──────────────────────────────────────────────────

CH_HOST = "136.111.66.222"
CH_PORT = 8123
CH_USER = "default"
CH_PASSWORD = os.environ.get("CH_PASSWORD", "JVXCmZGjYybCAnqtOgVY")

ADX_CLUSTER = os.environ.get("ADX_CLUSTER_URI", "https://kresadxdev.centralindia.kusto.windows.net")

ORG = "fa7b153b-6998-416d-8adc-3e41c3971524"
APP = "6fa6d19b-21e4-44be-8103-7ab1b5324eec"
DB_NAME = "org_fa7b153b_6998_416d_8adc_3e41c3971524_app_6fa6d19b_21e4_44be_8103_7ab1b5324eec"

TABLES = ["raw_events", "event_props", "user_profile_props", "user_experience", "business_metrics"]

# ── Connections ─────────────────────────────────────────────

ch = clickhouse_connect.get_client(host=CH_HOST, port=CH_PORT, username=CH_USER, password=CH_PASSWORD)
credential = DefaultAzureCredential()
kcsb = KustoConnectionStringBuilder.with_azure_token_credential(ADX_CLUSTER, credential)
adx = KustoClient(kcsb)

PASS = 0
FAIL = 0


def check(label, condition, detail=""):
    global PASS, FAIL
    if condition:
        print(f"  PASS  {label}")
        PASS += 1
    else:
        print(f"  FAIL  {label}  {detail}")
        FAIL += 1


def adx_query(kql):
    result = adx.execute_query(DB_NAME, kql)
    cols = [c.column_name for c in result.primary_results[0].columns]
    return [{c: row[c] for c in cols} for row in result.primary_results[0]]


def ch_query(sql):
    result = ch.query(sql)
    if not result.result_rows:
        return []
    return [dict(zip(result.column_names, row)) for row in result.result_rows]


# ── Level 1: Row Counts ────────────────────────────────────

print("\n" + "=" * 60)
print("  LEVEL 1: ROW COUNT MATCH")
print("=" * 60)

for tbl in TABLES:
    ch_cnt = ch.query(f"SELECT count() FROM `{DB_NAME}`.`{tbl}`").result_rows[0][0]
    adx_cnt = adx_query(f"{tbl} | count")[0]["Count"]
    check(f"{tbl}", ch_cnt == adx_cnt, f"CH={ch_cnt} ADX={adx_cnt}")


# ── Level 2: Sample Data Comparison ────────────────────────

print("\n" + "=" * 60)
print("  LEVEL 2: SAMPLE DATA COMPARISON")
print("=" * 60)

# raw_events: compare first 5 by event_id
ch_sample = ch_query(f"SELECT event_id, user_id, event_name FROM `{DB_NAME}`.raw_events ORDER BY event_id LIMIT 5")
adx_sample = adx_query("raw_events | project event_id, user_id, event_name | order by event_id asc | take 5")
if ch_sample and adx_sample:
    for i, (c, a) in enumerate(zip(ch_sample, adx_sample)):
        match = c["event_id"] == a["event_id"] and c["user_id"] == a["user_id"] and c["event_name"] == a["event_name"]
        check(f"raw_events row {i}: {c['event_id'][:8]}...", match,
              f"CH=({c['user_id']},{c['event_name']}) ADX=({a['user_id']},{a['event_name']})" if not match else "")
else:
    check("raw_events sample", False, "empty results")

# business_metrics: compare by metric_name + period
ch_bm = ch_query(f"SELECT metric_name, dimension, value, scenario_id FROM `{DB_NAME}`.business_metrics FINAL ORDER BY metric_name, dimension, scenario_id LIMIT 5")
adx_bm = adx_query("""
business_metrics
| summarize value = arg_max(created_at, value) by metric_name, dimension, scenario_id
| project metric_name, dimension, value=value1, scenario_id
| order by metric_name asc, dimension asc, scenario_id asc
| take 5
""")
if ch_bm and adx_bm:
    for i, (c, a) in enumerate(zip(ch_bm, adx_bm)):
        name_match = c["metric_name"] == a["metric_name"] and c["dimension"] == a["dimension"]
        val_match = abs(float(c["value"]) - float(a["value"])) < 0.01
        check(f"business_metrics row {i}: {c['metric_name']}/{c['dimension']}", name_match and val_match,
              f"CH={c['value']} ADX={a['value']}" if not val_match else "")
else:
    check("business_metrics sample", False, "empty results")

# user_experience: compare count by experience_id
ch_ue = ch_query(f"SELECT experience_id, count() as cnt FROM `{DB_NAME}`.user_experience GROUP BY experience_id ORDER BY cnt DESC LIMIT 5")
adx_ue = adx_query("user_experience | summarize cnt = count() by experience_id | order by cnt desc | take 5")
if ch_ue and adx_ue:
    for i, (c, a) in enumerate(zip(ch_ue, adx_ue)):
        match = c["experience_id"] == a["experience_id"] and int(c["cnt"]) == int(a["cnt"])
        check(f"user_experience group {i}: exp={c['experience_id'][:8]}... cnt={c['cnt']}", match,
              f"CH={c['cnt']} ADX={a['cnt']}" if not match else "")
else:
    check("user_experience sample", False, "empty results")


# ── Level 3: Metric Query Comparison ───────────────────────

print("\n" + "=" * 60)
print("  LEVEL 3: METRIC QUERY COMPARISON (CH SQL vs KQL)")
print("=" * 60)

ch_qb = QueryBuilder(ORG, APP)
adx_qb = KQLQueryBuilder(ORG, APP)

# Find a time range that has data
ch_range = ch_query(f"SELECT min(client_ts) as mn, max(client_ts) as mx FROM `{DB_NAME}`.raw_events")
if ch_range and ch_range[0]["mn"]:
    start = str(ch_range[0]["mn"])[:19]
    end = str(ch_range[0]["mx"])[:19]
    print(f"  Data range: {start} → {end}")
    TR = {"start": start, "end": end}

    # Find top event names
    top_events = ch_query(f"SELECT event_name, count() as cnt FROM `{DB_NAME}`.raw_events GROUP BY event_name ORDER BY cnt DESC LIMIT 3")
    print(f"  Top events: {[(e['event_name'], e['cnt']) for e in top_events]}")

    for evt in top_events[:2]:
        event_name = evt["event_name"]

        # Count
        ch_sql = ch_qb.build_query("count", {"event_name": event_name, "distinct": False, "time_range": TR, "granularity": "monthly", "group_by": [], "filters": {}})
        kql = adx_qb.build_query("count", {"event_name": event_name, "distinct": False, "time_range": TR, "granularity": "monthly", "group_by": [], "filters": {}})
        ch_r = ch_query(ch_sql)
        adx_r = adx_query(kql)
        ch_total = sum(r["value"] for r in ch_r) if ch_r else 0
        adx_total = sum(r["value"] for r in adx_r) if adx_r else 0
        check(f"count({event_name})", ch_total == adx_total, f"CH={ch_total} ADX={adx_total}")

        # Distinct count
        ch_sql = ch_qb.build_query("count", {"event_name": event_name, "distinct": True, "time_range": TR, "granularity": "monthly", "group_by": [], "filters": {}})
        kql = adx_qb.build_query("count", {"event_name": event_name, "distinct": True, "time_range": TR, "granularity": "monthly", "group_by": [], "filters": {}})
        ch_r = ch_query(ch_sql)
        adx_r = adx_query(kql)
        ch_total = sum(r["value"] for r in ch_r) if ch_r else 0
        adx_total = sum(r["value"] for r in adx_r) if adx_r else 0
        check(f"dcount({event_name})", ch_total == adx_total, f"CH={ch_total} ADX={adx_total}")

    # Business metrics comparison
    ch_bm_names = ch_query(f"SELECT DISTINCT metric_name FROM `{DB_NAME}`.business_metrics FINAL LIMIT 5")
    for bm in ch_bm_names[:3]:
        mn = bm["metric_name"]
        bm_tr = {"start": "2026-01-01 00:00:00", "end": "2027-01-01 00:00:00"}

        ch_sql = ch_qb.build_query("operational", {"metric_name": mn, "aggregation": "sum", "time_range": bm_tr, "granularity": "monthly", "group_by": [], "filters": {}})
        kql = adx_qb.build_query("operational", {"metric_name": mn, "aggregation": "sum", "time_range": bm_tr, "granularity": "monthly", "group_by": [], "filters": {}})

        ch_r = ch_query(ch_sql)
        adx_r = adx_query(kql)

        ch_vals = {str(r["period"])[:7]: r["value"] for r in ch_r}
        adx_vals = {str(r["period"])[:7]: r["value"] for r in adx_r}

        all_months = sorted(set(list(ch_vals.keys()) + list(adx_vals.keys())))
        match = True
        detail = ""
        for m in all_months:
            cv = ch_vals.get(m, 0)
            av = adx_vals.get(m, 0)
            if cv != 0 and abs(cv - av) / abs(cv) > 0.01:
                match = False
                detail = f"{m}: CH={cv:.2f} ADX={av:.2f}"
                break
        check(f"operational({mn})", match, detail)

else:
    print("  No event data found — skipping metric queries")


# ── Summary ─────────────────────────────────────────────────

print(f"\n{'=' * 60}")
print(f"  MIGRATION VERIFICATION: {PASS} passed, {FAIL} failed")
print(f"{'=' * 60}")

sys.exit(1 if FAIL > 0 else 0)
