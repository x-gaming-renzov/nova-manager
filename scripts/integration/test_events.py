"""Steps 14-17: Track events, wait for worker, verify via metrics compute."""

import json
import time

import requests
from scripts.integration.helpers import RUN_ID, step, check


def run(base: str, state: dict):
    api = f"{base}/api/v1"
    headers = state["headers"]
    sdk_headers = state["sdk_headers"]

    # ── Track Events ─────────────────────────────────────
    step(14, "SDK — Track Events (Redis → Worker → ClickHouse)")

    events = [
        {
            "user_id": f"smoke_user_{RUN_ID}",
            "event_name": "smoke_button_click",
            "event_data": {"button_id": "signup", "page": "home"},
            "timestamp": "2026-03-15T12:00:00Z",
        },
        {
            "user_id": f"smoke_user_{RUN_ID}",
            "event_name": "smoke_page_view",
            "event_data": {"page": "/dashboard", "referrer": "/home"},
            "timestamp": "2026-03-15T12:01:00Z",
        },
        {
            "user_id": f"smoke_user_{RUN_ID}",
            "event_name": "smoke_purchase",
            "event_data": {"item": "sword", "amount": "9.99", "currency": "USD"},
            "timestamp": "2026-03-15T12:02:00Z",
        },
    ]

    for event in events:
        r = requests.post(f"{api}/metrics/track-event/", headers=sdk_headers, json=event)
        check(f"Track {event['event_name']}", r.status_code == 200, f"got {r.status_code}")

    # ── Wait for Worker ──────────────────────────────────
    step(15, "Waiting for worker to process jobs...")
    for i in range(10, 0, -1):
        print(f"  {i}s...", end=" ", flush=True)
        time.sleep(1)
    print("done!")

    # ── Metrics Compute ──────────────────────────────────
    step(16, "Metrics — Compute (Worker + ClickHouse verification)")

    # Count
    r = requests.post(f"{api}/metrics/compute/", headers=headers, json={
        "type": "count",
        "config": {
            "event_name": "smoke_button_click",
            "distinct": False,
            "time_range": {"start": "2026-01-01T00:00:00", "end": "2026-12-31T23:59:59"},
            "granularity": "daily",
            "group_by": [],
            "filters": {},
        },
    })
    check("Metrics count returns 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        total = sum(row.get("value", 0) for row in data)
        check("Count has data (worker processed)", total >= 1, f"total={total}")
        print(f"  Response: {json.dumps(data, default=str)[:200]}")

    # Distinct count
    r = requests.post(f"{api}/metrics/compute/", headers=headers, json={
        "type": "count",
        "config": {
            "event_name": "smoke_page_view",
            "distinct": True,
            "time_range": {"start": "2026-01-01T00:00:00", "end": "2026-12-31T23:59:59"},
            "granularity": "monthly",
            "group_by": [],
            "filters": {},
        },
    })
    check("Metrics distinct count returns 200", r.status_code == 200, f"got {r.status_code}")

    # Aggregation SUM
    r = requests.post(f"{api}/metrics/compute/", headers=headers, json={
        "type": "aggregation",
        "config": {
            "event_name": "smoke_purchase",
            "property": "amount",
            "aggregation": "sum",
            "time_range": {"start": "2026-01-01T00:00:00", "end": "2026-12-31T23:59:59"},
            "granularity": "daily",
            "group_by": [],
            "filters": {},
        },
    })
    check("Metrics aggregation (SUM) returns 200", r.status_code == 200, f"got {r.status_code}")

    # Count with GROUP BY
    r = requests.post(f"{api}/metrics/compute/", headers=headers, json={
        "type": "count",
        "config": {
            "event_name": "smoke_button_click",
            "distinct": False,
            "time_range": {"start": "2026-01-01T00:00:00", "end": "2026-12-31T23:59:59"},
            "granularity": "daily",
            "group_by": [{"key": "page", "source": "event_properties"}],
            "filters": {},
        },
    })
    check("Metrics GROUP BY returns 200", r.status_code == 200, f"got {r.status_code}")

    # Ratio
    r = requests.post(f"{api}/metrics/compute/", headers=headers, json={
        "type": "ratio",
        "config": {
            "numerator": {"event_name": "smoke_purchase"},
            "denominator": {"event_name": "smoke_page_view"},
            "time_range": {"start": "2026-01-01T00:00:00", "end": "2026-12-31T23:59:59"},
            "granularity": "daily",
            "group_by": [],
            "filters": {},
        },
    })
    check("Metrics ratio returns 200", r.status_code == 200, f"got {r.status_code}")

    # ── Events Schema & Profile Keys ─────────────────────
    step(17, "Metrics — Events Schema & Profile Keys")

    r = requests.get(f"{api}/metrics/events-schema/", headers=headers)
    check("Events schema returns 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        check("Schema has entries", len(r.json()) >= 1, f"got {len(r.json())}")

    r = requests.get(f"{api}/metrics/user-profile-keys/", headers=headers)
    check("Profile keys returns 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        check("Profile keys has entries", len(r.json()) >= 1, f"got {len(r.json())}")
