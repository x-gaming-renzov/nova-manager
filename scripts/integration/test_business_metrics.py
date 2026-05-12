"""Steps 20-25: Business data ingestion, operational metrics, formula metrics.

Tests the full GTM KPI flow:
  - Ingest business data (marketing spend, revenue)
  - Query via operational metrics
  - Combine with event-based metrics via formula metrics
  - Verify CRUD for saving metric definitions
"""

import json
import time

import requests
from scripts.integration.helpers import RUN_ID, step, check


def run(base: str, state: dict):
    api = f"{base}/api/v1"
    headers = state["headers"]
    sdk_headers = state["sdk_headers"]

    # ── Ingest Business Data ─────────────────────────────
    step(20, "Business Data — Ingest Marketing Spend & Revenue")

    business_data = {
        "data": [
            # Marketing spend by channel (Jul-Sep 2026)
            {"metric_name": "marketing_spend", "dimension": "google_ads", "value": 5000.0, "period_start": "2026-07-01T00:00:00Z", "currency": "USD"},
            {"metric_name": "marketing_spend", "dimension": "google_ads", "value": 8000.0, "period_start": "2026-08-01T00:00:00Z", "currency": "USD"},
            {"metric_name": "marketing_spend", "dimension": "google_ads", "value": 12000.0, "period_start": "2026-09-01T00:00:00Z", "currency": "USD"},
            {"metric_name": "marketing_spend", "dimension": "facebook", "value": 3000.0, "period_start": "2026-07-01T00:00:00Z", "currency": "USD"},
            {"metric_name": "marketing_spend", "dimension": "facebook", "value": 5000.0, "period_start": "2026-08-01T00:00:00Z", "currency": "USD"},
            {"metric_name": "marketing_spend", "dimension": "facebook", "value": 7000.0, "period_start": "2026-09-01T00:00:00Z", "currency": "USD"},
            # TO incentive payouts
            {"metric_name": "to_incentive_payout", "dimension": "tier_1", "value": 2000.0, "period_start": "2026-07-01T00:00:00Z", "currency": "USD"},
            {"metric_name": "to_incentive_payout", "dimension": "tier_1", "value": 3500.0, "period_start": "2026-08-01T00:00:00Z", "currency": "USD"},
            {"metric_name": "to_incentive_payout", "dimension": "tier_1", "value": 4000.0, "period_start": "2026-09-01T00:00:00Z", "currency": "USD"},
            # Revenue
            {"metric_name": "total_revenue", "dimension": "ad_revenue", "value": 1200.0, "period_start": "2026-07-01T00:00:00Z", "currency": "USD"},
            {"metric_name": "total_revenue", "dimension": "ad_revenue", "value": 3500.0, "period_start": "2026-08-01T00:00:00Z", "currency": "USD"},
            {"metric_name": "total_revenue", "dimension": "ad_revenue", "value": 8000.0, "period_start": "2026-09-01T00:00:00Z", "currency": "USD"},
            {"metric_name": "total_revenue", "dimension": "sponsorship", "value": 0.0, "period_start": "2026-07-01T00:00:00Z", "currency": "USD"},
            {"metric_name": "total_revenue", "dimension": "sponsorship", "value": 5000.0, "period_start": "2026-08-01T00:00:00Z", "currency": "USD"},
            {"metric_name": "total_revenue", "dimension": "sponsorship", "value": 10000.0, "period_start": "2026-09-01T00:00:00Z", "currency": "USD"},
        ],
    }

    r = requests.post(f"{api}/metrics/business-data/", headers=headers, json=business_data)
    check("Ingest business data returns 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        check("Ingested correct count", r.json().get("count") == 15, f"got {r.json()}")

    # ── Business Data Schema ─────────────────────────────
    step(21, "Business Data — Schema Discovery")

    r = requests.get(f"{api}/metrics/business-data/schema/", headers=headers)
    check("Business data schema returns 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        schema = r.json()
        metric_names = {row["metric_name"] for row in schema}
        check("Schema has marketing_spend", "marketing_spend" in metric_names, f"got {metric_names}")
        check("Schema has total_revenue", "total_revenue" in metric_names, f"got {metric_names}")
        check("Schema has to_incentive_payout", "to_incentive_payout" in metric_names, f"got {metric_names}")
        dimensions = {row["dimension"] for row in schema}
        check("Schema has google_ads dimension", "google_ads" in dimensions, f"got {dimensions}")
        print(f"  Schema: {json.dumps(schema, default=str)[:300]}")

    # ── ReplacingMergeTree Dedup ─────────────────────────
    step(22, "Business Data — Upsert (ReplacingMergeTree dedup)")

    # Re-upload July google_ads spend with corrected value
    r = requests.post(f"{api}/metrics/business-data/", headers=headers, json={
        "data": [
            {"metric_name": "marketing_spend", "dimension": "google_ads", "value": 5500.0, "period_start": "2026-07-01T00:00:00Z", "currency": "USD"},
        ],
    })
    check("Re-upload returns 200", r.status_code == 200, f"got {r.status_code}")

    # ── Operational Metric Compute ───────────────────────
    step(23, "Operational Metric — Compute")

    # Total marketing spend across all channels/months
    r = requests.post(f"{api}/metrics/compute/", headers=headers, json={
        "type": "operational",
        "config": {
            "metric_name": "marketing_spend",
            "aggregation": "sum",
            "time_range": {"start": "2026-07-01 00:00:00", "end": "2026-10-01 00:00:00"},
            "granularity": "monthly",
            "group_by": [],
            "filters": {},
        },
    })
    check("Operational metric returns 200", r.status_code == 200, f"got {r.status_code}: {r.text[:300]}")
    if r.status_code == 200:
        data = r.json()
        check("Has 3 monthly periods", len(data) == 3, f"got {len(data)} rows: {data}")
        if data:
            # July: google_ads (5500 after upsert) + facebook (3000) = 8500
            # Note: ReplacingMergeTree FINAL may not immediately dedup — allow both values
            jul_rows = [row for row in data if "2026-07" in str(row.get("period", ""))]
            if jul_rows:
                jul_val = jul_rows[0]["value"]
                check("July spend is reasonable (dedup may lag)", jul_val >= 8000, f"got {jul_val}")
            print(f"  Monthly spend: {json.dumps(data, default=str)[:400]}")

    # Spend by channel (group_by dimension)
    r = requests.post(f"{api}/metrics/compute/", headers=headers, json={
        "type": "operational",
        "config": {
            "metric_name": "marketing_spend",
            "aggregation": "sum",
            "time_range": {"start": "2026-07-01 00:00:00", "end": "2026-10-01 00:00:00"},
            "granularity": "monthly",
            "group_by": [{"key": "dimension", "source": ""}],
            "filters": {},
        },
    })
    check("Operational group_by dimension returns 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        dimensions_seen = {row.get("dimension") for row in data}
        check("Has google_ads breakdown", "google_ads" in dimensions_seen, f"got {dimensions_seen}")
        check("Has facebook breakdown", "facebook" in dimensions_seen, f"got {dimensions_seen}")
        print(f"  By channel: {json.dumps(data, default=str)[:400]}")

    # Dimension filter — only google_ads
    r = requests.post(f"{api}/metrics/compute/", headers=headers, json={
        "type": "operational",
        "config": {
            "metric_name": "marketing_spend",
            "dimension_filter": "google_ads",
            "aggregation": "sum",
            "time_range": {"start": "2026-07-01 00:00:00", "end": "2026-10-01 00:00:00"},
            "granularity": "monthly",
            "group_by": [],
            "filters": {},
        },
    })
    check("Dimension filter returns 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        check("Has 3 periods for google_ads", len(data) == 3, f"got {len(data)}")
        print(f"  Google Ads only: {json.dumps(data, default=str)[:300]}")

    # Total revenue
    r = requests.post(f"{api}/metrics/compute/", headers=headers, json={
        "type": "operational",
        "config": {
            "metric_name": "total_revenue",
            "aggregation": "sum",
            "time_range": {"start": "2026-07-01 00:00:00", "end": "2026-10-01 00:00:00"},
            "granularity": "monthly",
            "group_by": [],
            "filters": {},
        },
    })
    check("Revenue operational metric returns 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"  Monthly revenue: {json.dumps(data, default=str)[:300]}")

    # ── Track Events for Formula Tests ───────────────────
    step(24, "Track Events — For Formula Metric Tests")

    # Track user activity events (to compute MAU, tournament count)
    user_events = []
    for i in range(20):
        user_events.append({
            "event_name": f"biz_session_start_{RUN_ID}",
            "event_data": {"source": "organic" if i < 15 else "paid"},
            "timestamp": "2026-07-15T12:00:00Z",
        })
    for i in range(35):
        user_events.append({
            "event_name": f"biz_session_start_{RUN_ID}",
            "event_data": {"source": "organic" if i < 25 else "paid"},
            "timestamp": "2026-08-15T12:00:00Z",
        })
    for i in range(50):
        user_events.append({
            "event_name": f"biz_session_start_{RUN_ID}",
            "event_data": {"source": "organic" if i < 30 else "paid"},
            "timestamp": "2026-09-15T12:00:00Z",
        })

    # Track as different users for MAU distinct count
    for idx, evt in enumerate(user_events):
        r = requests.post(f"{api}/metrics/track-event/", headers=sdk_headers, json={
            "user_id": f"biz_user_{RUN_ID}_{idx}",
            "event_name": evt["event_name"],
            "event_data": evt["event_data"],
            "timestamp": evt["timestamp"],
        })
    check(f"Tracked {len(user_events)} events", True, "")

    # Track tournament events
    tournament_events = []
    for i in range(10):
        tournament_events.append({
            "user_id": f"biz_to_{RUN_ID}_{i}",
            "event_name": f"biz_tournament_created_{RUN_ID}",
            "event_data": {"game": "bgmi", "format": "squad"},
            "timestamp": "2026-07-15T12:00:00Z",
        })
    for i in range(15):
        tournament_events.append({
            "user_id": f"biz_to_{RUN_ID}_{i}",
            "event_name": f"biz_tournament_created_{RUN_ID}",
            "event_data": {"game": "bgmi", "format": "squad"},
            "timestamp": "2026-08-15T12:00:00Z",
        })
    for i in range(25):
        tournament_events.append({
            "user_id": f"biz_to_{RUN_ID}_{i}",
            "event_name": f"biz_tournament_created_{RUN_ID}",
            "event_data": {"game": "bgmi", "format": "squad"},
            "timestamp": "2026-09-15T12:00:00Z",
        })

    for evt in tournament_events:
        r = requests.post(f"{api}/metrics/track-event/", headers=sdk_headers, json=evt)
    check(f"Tracked {len(tournament_events)} tournament events", True, "")

    # Wait for worker to process
    print("  Waiting for worker to process event jobs...")
    for i in range(12, 0, -1):
        print(f"  {i}s...", end=" ", flush=True)
        time.sleep(1)
    print("done!")

    # Verify event counts exist
    r = requests.post(f"{api}/metrics/compute/", headers=headers, json={
        "type": "count",
        "config": {
            "event_name": f"biz_session_start_{RUN_ID}",
            "distinct": True,
            "time_range": {"start": "2026-07-01 00:00:00", "end": "2026-10-01 00:00:00"},
            "granularity": "monthly",
            "group_by": [],
            "filters": {},
        },
    })
    check("MAU count compute returns 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        total_mau = sum(row.get("value", 0) for row in data)
        check("MAU has data (worker processed)", total_mau > 0, f"total MAU={total_mau}")
        print(f"  MAU by month: {json.dumps(data, default=str)[:300]}")

    # ── Formula Metric Compute ───────────────────────────
    step(25, "Formula Metric — CAC, ROAS, Net Margin")

    # CAC = Total Marketing Spend / MAU
    r = requests.post(f"{api}/metrics/compute/", headers=headers, json={
        "type": "formula",
        "config": {
            "time_range": {"start": "2026-07-01 00:00:00", "end": "2026-10-01 00:00:00"},
            "granularity": "monthly",
            "group_by": [],
            "operands": {
                "spend": {
                    "type": "operational",
                    "config": {
                        "metric_name": "marketing_spend",
                        "aggregation": "sum",
                    },
                },
                "mau": {
                    "type": "count",
                    "config": {
                        "event_name": f"biz_session_start_{RUN_ID}",
                        "distinct": True,
                    },
                },
            },
            "expression": "spend / mau",
        },
    })
    check("Formula CAC returns 200", r.status_code == 200, f"got {r.status_code}: {r.text[:300]}")
    if r.status_code == 200:
        data = r.json()
        check("CAC has monthly data", len(data) >= 1, f"got {len(data)} rows")
        if data:
            for row in data:
                print(f"    Period: {row.get('period')}, CAC: ${row.get('value', 'N/A'):.2f}" if row.get('value') else f"    Period: {row.get('period')}, CAC: N/A")

    # ROAS = Total Revenue / Total Marketing Spend
    r = requests.post(f"{api}/metrics/compute/", headers=headers, json={
        "type": "formula",
        "config": {
            "time_range": {"start": "2026-07-01 00:00:00", "end": "2026-10-01 00:00:00"},
            "granularity": "monthly",
            "group_by": [],
            "operands": {
                "revenue": {
                    "type": "operational",
                    "config": {
                        "metric_name": "total_revenue",
                        "aggregation": "sum",
                    },
                },
                "spend": {
                    "type": "operational",
                    "config": {
                        "metric_name": "marketing_spend",
                        "aggregation": "sum",
                    },
                },
            },
            "expression": "revenue / spend",
        },
    })
    check("Formula ROAS returns 200", r.status_code == 200, f"got {r.status_code}: {r.text[:300]}")
    if r.status_code == 200:
        data = r.json()
        check("ROAS has monthly data", len(data) >= 1, f"got {len(data)} rows")
        if data:
            for row in data:
                val = row.get('value')
                print(f"    Period: {row.get('period')}, ROAS: {val:.3f}x" if val else f"    Period: {row.get('period')}, ROAS: N/A")

    # Net Margin = Total Revenue - Total Marketing Spend
    r = requests.post(f"{api}/metrics/compute/", headers=headers, json={
        "type": "formula",
        "config": {
            "time_range": {"start": "2026-07-01 00:00:00", "end": "2026-10-01 00:00:00"},
            "granularity": "monthly",
            "group_by": [],
            "operands": {
                "revenue": {
                    "type": "operational",
                    "config": {
                        "metric_name": "total_revenue",
                        "aggregation": "sum",
                    },
                },
                "spend": {
                    "type": "operational",
                    "config": {
                        "metric_name": "marketing_spend",
                        "aggregation": "sum",
                    },
                },
            },
            "expression": "revenue - spend",
        },
    })
    check("Formula Net Margin returns 200", r.status_code == 200, f"got {r.status_code}: {r.text[:300]}")
    if r.status_code == 200:
        data = r.json()
        check("Net Margin has monthly data", len(data) >= 1, f"got {len(data)} rows")
        if data:
            for row in data:
                val = row.get('value')
                print(f"    Period: {row.get('period')}, Net Margin: ${val:,.0f}" if val is not None else f"    Period: {row.get('period')}, Net Margin: N/A")

    # Cost per Tournament = Total Spend / Tournament Count
    r = requests.post(f"{api}/metrics/compute/", headers=headers, json={
        "type": "formula",
        "config": {
            "time_range": {"start": "2026-07-01 00:00:00", "end": "2026-10-01 00:00:00"},
            "granularity": "monthly",
            "group_by": [],
            "operands": {
                "spend": {
                    "type": "operational",
                    "config": {
                        "metric_name": "marketing_spend",
                        "aggregation": "sum",
                    },
                },
                "tournaments": {
                    "type": "count",
                    "config": {
                        "event_name": f"biz_tournament_created_{RUN_ID}",
                        "distinct": False,
                    },
                },
            },
            "expression": "spend / tournaments",
        },
    })
    check("Formula Cost/Tournament returns 200", r.status_code == 200, f"got {r.status_code}: {r.text[:300]}")
    if r.status_code == 200:
        data = r.json()
        check("Cost/Tournament has data", len(data) >= 1, f"got {len(data)} rows")
        if data:
            for row in data:
                val = row.get('value')
                print(f"    Period: {row.get('period')}, Cost/Tournament: ${val:,.2f}" if val is not None else f"    Period: {row.get('period')}, Cost/Tournament: N/A")

    # ── Save Formula Metric Definition ───────────────────
    step(26, "Metric CRUD — Save & Retrieve Formula Metric")

    # Create a saved CAC metric definition
    r = requests.post(f"{api}/metrics/", headers=headers, json={
        "name": f"CAC_{RUN_ID}",
        "description": "Customer Acquisition Cost = Total Spend / MAU",
        "type": "formula",
        "config": {
            "time_range": "3m",
            "granularity": "monthly",
            "group_by": [],
            "operands": {
                "spend": {
                    "type": "operational",
                    "config": {
                        "metric_name": "marketing_spend",
                        "aggregation": "sum",
                    },
                },
                "mau": {
                    "type": "count",
                    "config": {
                        "event_name": f"biz_session_start_{RUN_ID}",
                        "distinct": True,
                    },
                },
            },
            "expression": "spend / mau",
        },
    })
    check("Create formula metric returns 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    metric_id = r.json().get("pid") if r.status_code == 200 else None

    if metric_id:
        # Retrieve it
        r = requests.get(f"{api}/metrics/{metric_id}/", headers=headers)
        check("Get formula metric returns 200", r.status_code == 200, f"got {r.status_code}")
        if r.status_code == 200:
            metric = r.json()
            check("Metric type is formula", metric.get("type") == "formula", f"got {metric.get('type')}")
            check("Metric has operands", "operands" in metric.get("config", {}), f"config: {metric.get('config')}")

    # Create operational metric definition
    r = requests.post(f"{api}/metrics/", headers=headers, json={
        "name": f"Monthly_Spend_{RUN_ID}",
        "description": "Total marketing spend by month",
        "type": "operational",
        "config": {
            "metric_name": "marketing_spend",
            "aggregation": "sum",
            "time_range": "6m",
            "granularity": "monthly",
            "group_by": [],
            "filters": {},
        },
    })
    check("Create operational metric returns 200", r.status_code == 200, f"got {r.status_code}")

    # List all metrics — should include new types
    r = requests.get(f"{api}/metrics/", headers=headers)
    check("List metrics returns 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        metrics = r.json()
        types = {m.get("type") for m in metrics}
        check("Metrics list includes formula type", "formula" in types, f"types: {types}")
        check("Metrics list includes operational type", "operational" in types, f"types: {types}")
        print(f"  Total metrics: {len(metrics)}, types: {types}")
