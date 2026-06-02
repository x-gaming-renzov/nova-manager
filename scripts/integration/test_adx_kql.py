#!/usr/bin/env python3
"""
ADX/KQL Integration Test — runs all metric types against a real ADX database.

Usage:
    python scripts/integration/test_adx_kql.py

Requires:
    - ADX_CLUSTER_URI env var or defaults to kresadxdev
    - Azure auth (az login or AZURE_CLIENT_ID/SECRET/TENANT_ID env vars)

Uses org_test_db_check database. Cleans up test data before/after each run.
Does NOT touch production databases.
"""

import sys
import os
import uuid
from datetime import datetime

# ── ADX Connection ──────────────────────────────────────────

CLUSTER = os.getenv("ADX_CLUSTER_URI", "https://kresadxdev.centralindia.kusto.windows.net")
DB = "org_test_db_check"
RUN_ID = uuid.uuid4().hex[:8]

def get_client():
    from azure.kusto.data import KustoClient, KustoConnectionStringBuilder

    client_id = os.getenv("AZURE_CLIENT_ID")
    client_secret = os.getenv("AZURE_CLIENT_SECRET")
    tenant_id = os.getenv("AZURE_TENANT_ID")

    if client_id and client_secret and tenant_id:
        from azure.identity import ClientSecretCredential
        credential = ClientSecretCredential(tenant_id, client_id, client_secret)
    else:
        from azure.identity import DefaultAzureCredential
        credential = DefaultAzureCredential()

    kcsb = KustoConnectionStringBuilder.with_azure_token_credential(CLUSTER, credential)
    return KustoClient(kcsb)


# ── Test Harness ────────────────────────────────────────────

PASS = 0
FAIL = 0
ERRORS = []

def check(label, condition, detail=""):
    global PASS, FAIL, ERRORS
    if condition:
        print(f"  PASS  {label}")
        PASS += 1
    else:
        msg = f"  FAIL  {label}" + (f" — {detail}" if detail else "")
        print(msg)
        FAIL += 1
        ERRORS.append(label)


def query(client, kql):
    result = client.execute_query(DB, kql)
    cols = [c.column_name for c in result.primary_results[0].columns]
    return [{c: row[c] for c in cols} for row in result.primary_results[0]]


def mgmt(client, cmd):
    client.execute_mgmt(DB, cmd)


# ── Test Data ───────────────────────────────────────────────

def setup_tables(client):
    """Ensure tables exist with correct schema."""
    tables = {
        "raw_events": "(event_id: string, user_id: string, event_name: string, event_data: dynamic, client_ts: datetime, server_ts: datetime)",
        "event_props": "(event_id: string, user_id: string, event_name: string, key: string, value: string, client_ts: datetime, server_ts: datetime)",
        "user_profile_props": "(user_id: string, key: string, value: string, server_ts: datetime)",
        "user_experience": "(user_id: string, experience_id: string, personalisation_id: string, personalisation_name: string, experience_variant_id: string, features: dynamic, evaluation_reason: string, assigned_at: datetime)",
        "business_metrics": "(metric_name: string, dimension: string, value: real, currency: string, scenario_id: string, period_start: datetime, created_at: datetime)",
    }
    for name, schema in tables.items():
        mgmt(client, f".create-merge table {name} {schema}")


def clean_data(client):
    """Clear all test data."""
    for tbl in ["raw_events", "event_props", "user_profile_props", "user_experience", "business_metrics"]:
        try:
            mgmt(client, f".clear table {tbl} data")
        except Exception:
            pass


def ingest_test_data(client):
    """Ingest a known dataset for deterministic assertions."""

    # Raw events: 3 users, multiple events across 2 days
    mgmt(client, """.ingest inline into table raw_events <|
e01,u1,signup,,2026-07-01T10:00:00Z,2026-07-01T10:00:01Z
e02,u1,purchase,{"amount":100},2026-07-01T11:00:00Z,2026-07-01T11:00:01Z
e03,u2,signup,,2026-07-01T12:00:00Z,2026-07-01T12:00:01Z
e04,u2,purchase,{"amount":200},2026-07-01T13:00:00Z,2026-07-01T13:00:01Z
e05,u3,signup,,2026-07-01T14:00:00Z,2026-07-01T14:00:01Z
e06,u1,login,,2026-07-02T10:00:00Z,2026-07-02T10:00:01Z
e07,u2,login,,2026-07-02T11:00:00Z,2026-07-02T11:00:01Z
e08,u1,purchase,{"amount":50},2026-07-03T10:00:00Z,2026-07-03T10:00:01Z
e09,u3,purchase,{"amount":300},2026-07-15T10:00:00Z,2026-07-15T10:00:01Z
e10,u1,purchase,{"amount":75},2026-08-01T10:00:00Z,2026-08-01T10:00:01Z""")

    # Event props: flattened key-value pairs
    mgmt(client, """.ingest inline into table event_props <|
e02,u1,purchase,amount,100,2026-07-01T11:00:00Z,2026-07-01T11:00:01Z
e02,u1,purchase,currency,USD,2026-07-01T11:00:00Z,2026-07-01T11:00:01Z
e04,u2,purchase,amount,200,2026-07-01T13:00:00Z,2026-07-01T13:00:01Z
e04,u2,purchase,currency,USD,2026-07-01T13:00:00Z,2026-07-01T13:00:01Z
e08,u1,purchase,amount,50,2026-07-03T10:00:00Z,2026-07-03T10:00:01Z
e08,u1,purchase,currency,USD,2026-07-03T10:00:00Z,2026-07-03T10:00:01Z
e09,u3,purchase,amount,300,2026-07-15T10:00:00Z,2026-07-15T10:00:01Z
e09,u3,purchase,currency,EUR,2026-07-15T10:00:00Z,2026-07-15T10:00:01Z
e10,u1,purchase,amount,75,2026-08-01T10:00:00Z,2026-08-01T10:00:01Z
e10,u1,purchase,currency,USD,2026-08-01T10:00:00Z,2026-08-01T10:00:01Z""")

    # User profiles
    mgmt(client, """.ingest inline into table user_profile_props <|
u1,country,US,2026-07-01T10:00:00Z
u1,plan,free,2026-07-01T10:00:00Z
u2,country,IN,2026-07-01T12:00:00Z
u2,plan,premium,2026-07-01T12:00:00Z
u3,country,US,2026-07-01T14:00:00Z
u3,plan,free,2026-07-01T14:00:00Z
u1,plan,premium,2026-07-15T10:00:00Z""")

    # User experience assignments
    mgmt(client, """.ingest inline into table user_experience <|
u1,exp1,p1,control,v1,{},random,2026-07-01T10:00:00Z
u2,exp1,p2,variant_a,v2,{},random,2026-07-01T12:00:00Z
u3,exp1,p1,control,v1,{},random,2026-07-01T14:00:00Z""")

    # Business metrics
    mgmt(client, """.ingest inline into table business_metrics <|
marketing_spend,google_ads,5000,USD,actuals,2026-07-01T00:00:00Z,2026-07-01T00:00:00Z
marketing_spend,facebook,3000,USD,actuals,2026-07-01T00:00:00Z,2026-07-01T00:00:00Z
marketing_spend,google_ads,6000,USD,actuals,2026-08-01T00:00:00Z,2026-08-01T00:00:00Z
total_revenue,,15000,USD,actuals,2026-07-01T00:00:00Z,2026-07-01T00:00:00Z
total_revenue,,20000,USD,actuals,2026-08-01T00:00:00Z,2026-08-01T00:00:00Z
mau,,1000,,actuals,2026-07-01T00:00:00Z,2026-07-01T00:00:00Z
mau,,2000,,actuals,2026-08-01T00:00:00Z,2026-08-01T00:00:00Z
marketing_spend,google_ads,7000,USD,scenario_v2,2026-07-01T00:00:00Z,2026-07-01T00:00:00Z""")


# ── Tests ───────────────────────────────────────────────────

def test_count(client, qb):
    """Count events."""
    TR = {"start": "2026-07-01 00:00:00", "end": "2026-08-01 00:00:00"}

    # Total purchase events in July
    r = query(client, qb.build_query("count", {
        "event_name": "purchase", "distinct": False,
        "time_range": TR, "granularity": "monthly", "group_by": [], "filters": {},
    }))
    total = sum(row["value"] for row in r)
    check("count: 4 purchases in Jul", total == 4, f"got {total}")

    # Total signups
    r = query(client, qb.build_query("count", {
        "event_name": "signup", "distinct": False,
        "time_range": TR, "granularity": "monthly", "group_by": [], "filters": {},
    }))
    total = sum(row["value"] for row in r)
    check("count: 3 signups in Jul", total == 3, f"got {total}")

    # Daily granularity — purchases spread across days
    r = query(client, qb.build_query("count", {
        "event_name": "purchase", "distinct": False,
        "time_range": TR, "granularity": "daily", "group_by": [], "filters": {},
    }))
    check("count daily: multiple days", len(r) >= 2, f"got {len(r)} days")


def test_distinct_count(client, qb):
    """Distinct user count."""
    TR = {"start": "2026-07-01 00:00:00", "end": "2026-08-01 00:00:00"}

    r = query(client, qb.build_query("count", {
        "event_name": "purchase", "distinct": True,
        "time_range": TR, "granularity": "monthly", "group_by": [], "filters": {},
    }))
    total = sum(row["value"] for row in r)
    check("dcount: 3 unique purchasers in Jul", total == 3, f"got {total}")

    r = query(client, qb.build_query("count", {
        "event_name": "login", "distinct": True,
        "time_range": TR, "granularity": "monthly", "group_by": [], "filters": {},
    }))
    total = sum(row["value"] for row in r)
    check("dcount: 2 unique logins in Jul", total == 2, f"got {total}")


def test_aggregation(client, qb):
    """Aggregate event property values."""
    TR = {"start": "2026-07-01 00:00:00", "end": "2026-08-01 00:00:00"}

    # Sum of purchase amounts in July: 100 + 200 + 50 + 300 = 650
    r = query(client, qb.build_query("aggregation", {
        "event_name": "purchase", "property": "amount", "aggregation": "sum",
        "time_range": TR, "granularity": "monthly", "group_by": [], "filters": {},
    }))
    total = sum(row["value"] for row in r)
    check("agg sum(amount) Jul = 650", total == 650, f"got {total}")

    # Avg
    r = query(client, qb.build_query("aggregation", {
        "event_name": "purchase", "property": "amount", "aggregation": "avg",
        "time_range": TR, "granularity": "monthly", "group_by": [], "filters": {},
    }))
    total = sum(row["value"] for row in r)
    check("agg avg(amount) Jul = 162.5", abs(total - 162.5) < 0.1, f"got {total}")

    # Max
    r = query(client, qb.build_query("aggregation", {
        "event_name": "purchase", "property": "amount", "aggregation": "max",
        "time_range": TR, "granularity": "monthly", "group_by": [], "filters": {},
    }))
    val = max(row["value"] for row in r)
    check("agg max(amount) Jul = 300", val == 300, f"got {val}")


def test_group_by_event_property(client, qb):
    """Group by event property (currency)."""
    TR = {"start": "2026-07-01 00:00:00", "end": "2026-08-01 00:00:00"}

    r = query(client, qb.build_query("count", {
        "event_name": "purchase", "distinct": False,
        "time_range": TR, "granularity": "monthly",
        "group_by": [{"key": "currency", "source": "event_properties"}],
        "filters": {},
    }))
    currencies = {row.get("currency") for row in r}
    check("group_by event_prop: has USD", "USD" in currencies, f"got {currencies}")
    check("group_by event_prop: has EUR", "EUR" in currencies, f"got {currencies}")


def test_group_by_user_profile(client, qb):
    """Group by user profile attribute (country)."""
    TR = {"start": "2026-07-01 00:00:00", "end": "2026-08-01 00:00:00"}

    r = query(client, qb.build_query("count", {
        "event_name": "signup", "distinct": False,
        "time_range": TR, "granularity": "monthly",
        "group_by": [{"key": "country", "source": "user_profile"}],
        "filters": {},
    }))
    by_country = {row.get("country"): row["value"] for row in r}
    check("group_by user_profile: US=2", by_country.get("US") == 2, f"got {by_country}")
    check("group_by user_profile: IN=1", by_country.get("IN") == 1, f"got {by_country}")


def test_filter_event_property(client, qb):
    """Filter by event property."""
    TR = {"start": "2026-07-01 00:00:00", "end": "2026-08-01 00:00:00"}

    r = query(client, qb.build_query("count", {
        "event_name": "purchase", "distinct": False,
        "time_range": TR, "granularity": "monthly", "group_by": [],
        "filters": {"currency": {"source": "event_properties", "op": "=", "value": "EUR"}},
    }))
    total = sum(row["value"] for row in r)
    check("filter currency=EUR: 1 purchase", total == 1, f"got {total}")


def test_filter_user_profile(client, qb):
    """Filter by user profile."""
    TR = {"start": "2026-07-01 00:00:00", "end": "2026-08-01 00:00:00"}

    r = query(client, qb.build_query("count", {
        "event_name": "signup", "distinct": False,
        "time_range": TR, "granularity": "monthly", "group_by": [],
        "filters": {"country": {"source": "user_profile", "op": "=", "value": "US"}},
    }))
    total = sum(row["value"] for row in r)
    check("filter country=US: 2 signups", total == 2, f"got {total}")


def test_ratio(client, qb):
    """Ratio metric."""
    TR = {"start": "2026-07-01 00:00:00", "end": "2026-08-01 00:00:00"}

    # purchase users / signup users = 3/3 = 1.0
    r = query(client, qb.build_query("ratio", {
        "numerator": {"event_name": "purchase", "distinct": True},
        "denominator": {"event_name": "signup", "distinct": True},
        "time_range": TR, "granularity": "monthly", "group_by": [], "filters": {},
    }))
    check("ratio: has rows", len(r) >= 1, f"got {len(r)} rows")
    if r:
        check("ratio: purchase_users/signup_users = 1.0", r[0]["value"] == 1.0, f"got {r[0]['value']}")

    # login users / signup users = 2/3 ≈ 0.667
    r = query(client, qb.build_query("ratio", {
        "numerator": {"event_name": "login", "distinct": True},
        "denominator": {"event_name": "signup", "distinct": True},
        "time_range": TR, "granularity": "monthly", "group_by": [], "filters": {},
    }))
    if r:
        expected = 2.0 / 3.0
        check("ratio: login/signup ≈ 0.667", abs(r[0]["value"] - expected) < 0.01, f"got {r[0]['value']}")


def test_retention(client, qb):
    """Retention metric."""
    TR = {"start": "2026-07-01 00:00:00", "end": "2026-08-01 00:00:00"}

    # signup → login within 7 days: u1 and u2 logged in day after signup
    r = query(client, qb.build_query("retention", {
        "time_range": TR, "granularity": "daily", "group_by": [], "filters": {},
        "initial_event": {"event_name": "signup"},
        "return_event": {"event_name": "login"},
        "retention_window": "7d",
    }))
    check("retention: has rows", len(r) >= 1)
    if r:
        check("retention: has period", "period" in r[0])
        check("retention: has cohort_users", "cohort_users" in r[0])
        check("retention: has retained_users", "retained_users" in r[0])
        check("retention: has value", "value" in r[0])
        check("retention: cohort=3 (all signed up)", r[0]["cohort_users"] == 3, f"got {r[0].get('cohort_users')}")
        check("retention: retained=2 (u1,u2 logged in)", r[0]["retained_users"] == 2, f"got {r[0].get('retained_users')}")
        expected_value = 2.0 / 3.0
        check("retention: value ≈ 0.667", abs(r[0]["value"] - expected_value) < 0.01, f"got {r[0].get('value')}")


def test_retention_with_group_by(client, qb):
    """Retention with group_by user profile."""
    TR = {"start": "2026-07-01 00:00:00", "end": "2026-08-01 00:00:00"}

    r = query(client, qb.build_query("retention", {
        "time_range": TR, "granularity": "daily",
        "group_by": [{"key": "country", "source": "user_profile"}],
        "filters": {},
        "initial_event": {"event_name": "signup"},
        "return_event": {"event_name": "login"},
        "retention_window": "7d",
    }))
    check("retention+group_by: has rows", len(r) >= 1)
    if r:
        check("retention+group_by: has country column", "country" in r[0])


def test_operational(client, qb):
    """Operational (business_metrics) queries."""
    TR = {"start": "2026-07-01 00:00:00", "end": "2026-09-01 00:00:00"}

    # Total marketing spend July (actuals only): 5000 + 3000 = 8000
    r = query(client, qb.build_query("operational", {
        "metric_name": "marketing_spend", "aggregation": "sum",
        "scenario_id": "actuals",
        "time_range": TR, "granularity": "monthly", "group_by": [], "filters": {},
    }))
    jul = [row for row in r if str(row["period"])[:7] == "2026-07"]
    check("operational: Jul spend (actuals) = 8000", jul and jul[0]["value"] == 8000, f"got {jul}")

    # August: 6000
    aug = [row for row in r if str(row["period"])[:7] == "2026-08"]
    check("operational: Aug spend = 6000", aug and aug[0]["value"] == 6000, f"got {aug}")

    # Without scenario filter: sums all scenarios (5000+3000+7000=15000 for Jul)
    r = query(client, qb.build_query("operational", {
        "metric_name": "marketing_spend", "aggregation": "sum",
        "time_range": {"start": "2026-07-01 00:00:00", "end": "2026-08-01 00:00:00"},
        "granularity": "monthly", "group_by": [], "filters": {},
    }))
    check("operational: Jul all scenarios = 15000", r and r[0]["value"] == 15000, f"got {r}")

    # Dimension filter (actuals only)
    r = query(client, qb.build_query("operational", {
        "metric_name": "marketing_spend", "dimension_filter": "google_ads",
        "aggregation": "sum", "scenario_id": "actuals",
        "time_range": {"start": "2026-07-01 00:00:00", "end": "2026-08-01 00:00:00"},
        "granularity": "monthly", "group_by": [], "filters": {},
    }))
    check("operational: google_ads actuals Jul = 5000", r and r[0]["value"] == 5000, f"got {r}")

    # Group by dimension (actuals only)
    r = query(client, qb.build_query("operational", {
        "metric_name": "marketing_spend", "aggregation": "sum",
        "scenario_id": "actuals",
        "time_range": {"start": "2026-07-01 00:00:00", "end": "2026-08-01 00:00:00"},
        "granularity": "monthly",
        "group_by": [{"key": "dimension", "source": ""}],
        "filters": {},
    }))
    dims = {row["dimension"]: row["value"] for row in r}
    check("operational group_by: google=5000", dims.get("google_ads") == 5000, f"got {dims}")
    check("operational group_by: facebook=3000", dims.get("facebook") == 3000, f"got {dims}")

    # Scenario filter
    r = query(client, qb.build_query("operational", {
        "metric_name": "marketing_spend", "aggregation": "sum",
        "scenario_id": "scenario_v2",
        "time_range": {"start": "2026-07-01 00:00:00", "end": "2026-08-01 00:00:00"},
        "granularity": "monthly", "group_by": [], "filters": {},
    }))
    check("operational scenario_v2 = 7000", r and r[0]["value"] == 7000, f"got {r}")


def test_formula_division(client, qb):
    """Formula: CAC = spend / mau."""
    TR = {"start": "2026-07-01 00:00:00", "end": "2026-09-01 00:00:00"}

    r = query(client, qb.build_query("formula", {
        "time_range": TR, "granularity": "monthly", "group_by": [],
        "operands": {
            "spend": {"type": "operational", "config": {"metric_name": "marketing_spend", "aggregation": "sum", "scenario_id": "actuals"}},
            "mau": {"type": "operational", "config": {"metric_name": "mau", "aggregation": "sum"}},
        },
        "expression": "spend / mau",
    }))
    jul = [row for row in r if str(row["period"])[:7] == "2026-07"]
    # CAC Jul = 8000 / 1000 = 8.0
    check("formula CAC Jul = 8.0", jul and jul[0]["value"] == 8.0, f"got {jul}")

    aug = [row for row in r if str(row["period"])[:7] == "2026-08"]
    # CAC Aug = 6000 / 2000 = 3.0
    check("formula CAC Aug = 3.0", aug and aug[0]["value"] == 3.0, f"got {aug}")


def test_formula_subtraction(client, qb):
    """Formula: Net Margin = revenue - spend."""
    TR = {"start": "2026-07-01 00:00:00", "end": "2026-09-01 00:00:00"}

    r = query(client, qb.build_query("formula", {
        "time_range": TR, "granularity": "monthly", "group_by": [],
        "operands": {
            "rev": {"type": "operational", "config": {"metric_name": "total_revenue", "aggregation": "sum", "scenario_id": "actuals"}},
            "spend": {"type": "operational", "config": {"metric_name": "marketing_spend", "aggregation": "sum", "scenario_id": "actuals"}},
        },
        "expression": "rev - spend",
    }))
    jul = [row for row in r if str(row["period"])[:7] == "2026-07"]
    # Jul: 15000 - 8000 = 7000
    check("formula margin Jul = 7000", jul and jul[0]["value"] == 7000, f"got {jul}")


def test_formula_mixed_operands(client, qb):
    """Formula mixing operational + count operands."""
    TR = {"start": "2026-07-01 00:00:00", "end": "2026-08-01 00:00:00"}

    r = query(client, qb.build_query("formula", {
        "time_range": TR, "granularity": "monthly", "group_by": [],
        "operands": {
            "spend": {"type": "operational", "config": {"metric_name": "marketing_spend", "aggregation": "sum", "scenario_id": "actuals"}},
            "users": {"type": "count", "config": {"event_name": "signup", "distinct": True}},
        },
        "expression": "spend / users",
    }))
    # Jul actuals: 8000 / 3 ≈ 2666.67
    check("formula mixed: spend/users has rows", len(r) >= 1)
    if r:
        expected = 8000.0 / 3.0
        check("formula mixed: ≈ 2666.67", abs(r[0]["value"] - expected) < 1, f"got {r[0]['value']}")


def test_formula_three_operands(client, qb):
    """Formula with 3 operands: (revenue - spend) / mau."""
    TR = {"start": "2026-07-01 00:00:00", "end": "2026-08-01 00:00:00"}

    r = query(client, qb.build_query("formula", {
        "time_range": TR, "granularity": "monthly", "group_by": [],
        "operands": {
            "rev": {"type": "operational", "config": {"metric_name": "total_revenue", "aggregation": "sum", "scenario_id": "actuals"}},
            "spend": {"type": "operational", "config": {"metric_name": "marketing_spend", "aggregation": "sum", "scenario_id": "actuals"}},
            "mau": {"type": "operational", "config": {"metric_name": "mau", "aggregation": "sum"}},
        },
        "expression": "(rev - spend) / mau",
    }))
    # Jul actuals: (15000 - 8000) / 1000 = 7.0
    check("formula 3-op: has rows", len(r) >= 1)
    if r:
        check("formula 3-op: (rev-spend)/mau = 7.0", r[0]["value"] == 7.0, f"got {r[0]['value']}")


def test_relative_time_range(client, qb):
    """Relative time range (e.g. '30d')."""
    r = query(client, qb.build_query("count", {
        "event_name": "purchase", "distinct": False,
        "time_range": "365d", "granularity": "monthly", "group_by": [], "filters": {},
    }))
    check("relative time range: no error", r is not None)


def test_all_granularities(client, qb):
    """All time granularities produce valid output."""
    TR = {"start": "2026-07-01 00:00:00", "end": "2026-08-01 00:00:00"}

    for gran in ["hourly", "daily", "weekly", "monthly"]:
        r = query(client, qb.build_query("count", {
            "event_name": "purchase", "distinct": False,
            "time_range": TR, "granularity": gran, "group_by": [], "filters": {},
        }))
        check(f"granularity {gran}: has rows", len(r) >= 1)


def test_user_experience_group_by(client, qb):
    """Group by user experience attribute."""
    TR = {"start": "2026-07-01 00:00:00", "end": "2026-08-01 00:00:00"}

    r = query(client, qb.build_query("count", {
        "event_name": "signup", "distinct": False,
        "time_range": TR, "granularity": "monthly",
        "group_by": [{"key": "personalisation_name", "source": "user_experience"}],
        "filters": {},
    }))
    check("group_by user_experience: has rows", len(r) >= 1)
    if r:
        names = {row.get("personalisation_name") for row in r}
        check("group_by user_experience: has control", "control" in names, f"got {names}")


# ── Main ────────────────────────────────────────────────────

def main():
    global PASS, FAIL

    print(f"ADX KQL Integration Test — DB: {DB}")
    print(f"{'=' * 60}")

    client = get_client()

    # Setup
    print("\n[setup] Creating tables and ingesting test data...")
    setup_tables(client)
    clean_data(client)
    ingest_test_data(client)

    # Verify data
    for tbl, expected in [("raw_events", 10), ("event_props", 10), ("user_profile_props", 7), ("user_experience", 3), ("business_metrics", 8)]:
        cnt = query(client, f"{tbl} | count")[0]["Count"]
        check(f"setup {tbl} = {expected} rows", cnt == expected, f"got {cnt}")

    # Run tests
    from nova_manager.components.metrics.kql_query_builder import KQLQueryBuilder
    qb = KQLQueryBuilder("test", "test")

    tests = [
        ("Count", test_count),
        ("Distinct Count", test_distinct_count),
        ("Aggregation", test_aggregation),
        ("Group By Event Property", test_group_by_event_property),
        ("Group By User Profile", test_group_by_user_profile),
        ("Filter Event Property", test_filter_event_property),
        ("Filter User Profile", test_filter_user_profile),
        ("Ratio", test_ratio),
        ("Retention", test_retention),
        ("Retention + Group By", test_retention_with_group_by),
        ("Operational", test_operational),
        ("Formula Division", test_formula_division),
        ("Formula Subtraction", test_formula_subtraction),
        ("Formula Mixed Operands", test_formula_mixed_operands),
        ("Formula 3 Operands", test_formula_three_operands),
        ("Relative Time Range", test_relative_time_range),
        ("All Granularities", test_all_granularities),
        ("User Experience Group By", test_user_experience_group_by),
    ]

    for name, fn in tests:
        print(f"\n[{name}]")
        try:
            fn(client, qb)
        except Exception as e:
            FAIL += 1
            ERRORS.append(f"{name}: EXCEPTION {e}")
            print(f"  EXCEPTION: {e}")

    # Cleanup
    print("\n[cleanup] Clearing test data...")
    clean_data(client)

    # Summary
    print(f"\n{'=' * 60}")
    print(f"  RESULTS: {PASS} passed, {FAIL} failed")
    if ERRORS:
        print(f"\n  Failures:")
        for e in ERRORS:
            print(f"    - {e}")
    print(f"{'=' * 60}")

    return 1 if FAIL > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
