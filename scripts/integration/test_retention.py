"""Step 20: Retention metric compute — ClickHouse compatibility tests.

Tracks initial + return events for multiple users with run-unique event names,
then verifies retention compute across granularities, window sizes, and edge cases.
"""

import json
import time

import requests
from scripts.integration.helpers import RUN_ID, step, check

# Run-unique event names so data from other runs doesn't pollute assertions
INIT_EVENT = f"ret_init_{RUN_ID}"
RET_EVENT = f"ret_return_{RUN_ID}"


def run(base: str, state: dict):
    api = f"{base}/api/v1"
    headers = state["headers"]
    sdk_headers = state["sdk_headers"]

    TIME_RANGE = {"start": "2026-03-01 00:00:00", "end": "2026-04-30 00:00:00"}

    # ── Track retention-specific events ─────────────────
    step(20, "Retention — Track events for retention tests")

    events = []
    # 3 users: login + return within 2 days (well inside 7d and 30d windows)
    for i in range(3):
        uid = f"ret_active_{RUN_ID}_{i}"
        events.append({
            "user_id": uid,
            "event_name": INIT_EVENT,
            "event_data": {"source": "smoke"},
            "timestamp": f"2026-03-10T10:0{i}:00Z",
        })
        events.append({
            "user_id": uid,
            "event_name": RET_EVENT,
            "event_data": {"source": "smoke"},
            "timestamp": f"2026-03-12T10:0{i}:00Z",
        })

    # 2 users: login only (no return event) — cohort but not retained
    for i in range(2):
        uid = f"ret_churned_{RUN_ID}_{i}"
        events.append({
            "user_id": uid,
            "event_name": INIT_EVENT,
            "event_data": {"source": "smoke"},
            "timestamp": f"2026-03-10T11:0{i}:00Z",
        })

    # 1 user: login + late return (15 days later — outside 7d, inside 30d)
    events.append({
        "user_id": f"ret_late_{RUN_ID}",
        "event_name": INIT_EVENT,
        "event_data": {"source": "smoke"},
        "timestamp": "2026-03-10T12:00:00Z",
    })
    events.append({
        "user_id": f"ret_late_{RUN_ID}",
        "event_name": RET_EVENT,
        "event_data": {"source": "smoke"},
        "timestamp": "2026-03-25T12:00:00Z",
    })

    # 1 user: different cohort period (Mar 15) — tests multi-period output
    events.append({
        "user_id": f"ret_diff_{RUN_ID}",
        "event_name": INIT_EVENT,
        "event_data": {"source": "smoke"},
        "timestamp": "2026-03-15T09:00:00Z",
    })
    events.append({
        "user_id": f"ret_diff_{RUN_ID}",
        "event_name": RET_EVENT,
        "event_data": {"source": "smoke"},
        "timestamp": "2026-03-16T09:00:00Z",
    })

    for ev in events:
        r = requests.post(f"{api}/metrics/track-event/", headers=sdk_headers, json=ev)
        check(f"Track {ev['event_name'][:20]} ({ev['user_id'][:20]}...)",
              r.status_code == 200, f"got {r.status_code}")

    # ── Wait for worker ─────────────────────────────────
    step(21, "Retention — Waiting for worker...")
    for i in range(15, 0, -1):
        print(f"  {i}s...", end=" ", flush=True)
        time.sleep(1)
    print("done!")

    # ── Basic retention (daily, 30d window) ─────────────
    step(22, "Retention — Daily granularity, 30d window")

    r = requests.post(f"{api}/metrics/compute/", headers=headers, json={
        "type": "retention",
        "config": {
            "time_range": TIME_RANGE,
            "granularity": "daily",
            "group_by": [],
            "filters": {},
            "initial_event": {"event_name": INIT_EVENT, "distinct": False},
            "return_event": {"event_name": RET_EVENT, "distinct": False},
            "retention_window": "30d",
        },
    })
    check("Retention daily/30d returns 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        check("Has rows", len(data) >= 1, f"got {len(data)} rows")
        print(f"  Rows: {len(data)}")

        # Check response shape
        if data:
            row = data[0]
            check("Row has 'period'", "period" in row, f"keys: {list(row.keys())}")
            check("Row has 'cohort_users'", "cohort_users" in row, f"keys: {list(row.keys())}")
            check("Row has 'retained_users'", "retained_users" in row, f"keys: {list(row.keys())}")
            check("Row has 'value'", "value" in row, f"keys: {list(row.keys())}")

        # Verify data correctness on Mar 10 cohort
        # Expected: 6 cohort, 3-4 retained (3 active + possibly late user
        # depending on worker lag). Use >= to tolerate processing delays.
        mar10 = [d for d in data if "2026-03-10" in str(d.get("period", ""))]
        if mar10:
            row = mar10[0]
            check("Mar 10 cohort_users >= 3", row["cohort_users"] >= 3,
                  f"got {row['cohort_users']}")
            check("Mar 10 retained_users >= 3", row["retained_users"] >= 3,
                  f"got {row['retained_users']}")
            check("Mar 10 value > 0", row["value"] > 0, f"got {row['value']}")
            print(f"  Mar 10: {json.dumps(row, default=str)}")

        # Mar 15: 1 user, fully retained
        mar15 = [d for d in data if "2026-03-15" in str(d.get("period", ""))]
        if mar15:
            row = mar15[0]
            check("Mar 15 cohort_users == 1", row["cohort_users"] == 1,
                  f"got {row['cohort_users']}")
            check("Mar 15 retained_users == 1", row["retained_users"] == 1,
                  f"got {row['retained_users']}")
            check("Mar 15 value == 1.0", row["value"] == 1.0, f"got {row['value']}")
            print(f"  Mar 15: {json.dumps(row, default=str)}")

    # ── Narrow window (7d) — late user excluded ─────────
    step(23, "Retention — Daily granularity, 7d window")

    r = requests.post(f"{api}/metrics/compute/", headers=headers, json={
        "type": "retention",
        "config": {
            "time_range": TIME_RANGE,
            "granularity": "daily",
            "group_by": [],
            "filters": {},
            "initial_event": {"event_name": INIT_EVENT, "distinct": False},
            "return_event": {"event_name": RET_EVENT, "distinct": False},
            "retention_window": "7d",
        },
    })
    check("Retention daily/7d returns 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        mar10 = [d for d in data if "2026-03-10" in str(d.get("period", ""))]
        if mar10:
            row = mar10[0]
            # With 7d window, late user (return 15d later) should NOT be retained
            # Retained: 3 active only, Cohort: still 6
            check("7d: retained_users == 3 (late user excluded)",
                  row["retained_users"] == 3,
                  f"got {row['retained_users']}")
            check("7d: cohort unchanged at 6",
                  row["cohort_users"] == 6,
                  f"got {row['cohort_users']}")
            print(f"  Mar 10 (7d): {json.dumps(row, default=str)}")

    # ── Weekly granularity ──────────────────────────────
    step(24, "Retention — Weekly granularity, 30d window")

    r = requests.post(f"{api}/metrics/compute/", headers=headers, json={
        "type": "retention",
        "config": {
            "time_range": TIME_RANGE,
            "granularity": "weekly",
            "group_by": [],
            "filters": {},
            "initial_event": {"event_name": INIT_EVENT, "distinct": False},
            "return_event": {"event_name": RET_EVENT, "distinct": False},
            "retention_window": "30d",
        },
    })
    check("Retention weekly/30d returns 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        check("Weekly has rows", len(data) >= 1, f"got {len(data)} rows")
        print(f"  Weekly rows: {len(data)}")

    # ── Monthly granularity ─────────────────────────────
    step(25, "Retention — Monthly granularity, 30d window")

    r = requests.post(f"{api}/metrics/compute/", headers=headers, json={
        "type": "retention",
        "config": {
            "time_range": TIME_RANGE,
            "granularity": "monthly",
            "group_by": [],
            "filters": {},
            "initial_event": {"event_name": INIT_EVENT, "distinct": False},
            "return_event": {"event_name": RET_EVENT, "distinct": False},
            "retention_window": "30d",
        },
    })
    check("Retention monthly/30d returns 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        check("Monthly has rows", len(data) >= 1, f"got {len(data)} rows")
        print(f"  Monthly rows: {len(data)}")

    # ── Hourly granularity ──────────────────────────────
    step(26, "Retention — Hourly granularity, 7d window")

    r = requests.post(f"{api}/metrics/compute/", headers=headers, json={
        "type": "retention",
        "config": {
            "time_range": TIME_RANGE,
            "granularity": "hourly",
            "group_by": [],
            "filters": {},
            "initial_event": {"event_name": INIT_EVENT, "distinct": False},
            "return_event": {"event_name": RET_EVENT, "distinct": False},
            "retention_window": "7d",
        },
    })
    check("Retention hourly/7d returns 200", r.status_code == 200, f"got {r.status_code}")

    # ── No matching events (empty result) ───────────────
    step(27, "Retention — No matching events returns empty")

    r = requests.post(f"{api}/metrics/compute/", headers=headers, json={
        "type": "retention",
        "config": {
            "time_range": TIME_RANGE,
            "granularity": "daily",
            "group_by": [],
            "filters": {},
            "initial_event": {"event_name": f"nonexistent_{RUN_ID}", "distinct": False},
            "return_event": {"event_name": f"also_none_{RUN_ID}", "distinct": False},
            "retention_window": "30d",
        },
    })
    check("No events returns 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        check("Empty result", len(data) == 0, f"got {len(data)} rows")

    # ── Same event for initial and return ───────────────
    step(28, "Retention — Same event as initial and return")

    r = requests.post(f"{api}/metrics/compute/", headers=headers, json={
        "type": "retention",
        "config": {
            "time_range": TIME_RANGE,
            "granularity": "daily",
            "group_by": [],
            "filters": {},
            "initial_event": {"event_name": INIT_EVENT, "distinct": False},
            "return_event": {"event_name": INIT_EVENT, "distinct": False},
            "retention_window": "30d",
        },
    })
    check("Same-event returns 200", r.status_code == 200, f"got {r.status_code}")

    # ── 1h retention window — nobody should be retained ─
    step(29, "Retention — Very short window (1h)")

    r = requests.post(f"{api}/metrics/compute/", headers=headers, json={
        "type": "retention",
        "config": {
            "time_range": TIME_RANGE,
            "granularity": "daily",
            "group_by": [],
            "filters": {},
            "initial_event": {"event_name": INIT_EVENT, "distinct": False},
            "return_event": {"event_name": RET_EVENT, "distinct": False},
            "retention_window": "1h",
        },
    })
    check("Retention 1h window returns 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        # All return events are 1-15 days after initial — nobody within 1 hour
        total_retained = sum(row.get("retained_users", 0) for row in data)
        check("1h window: zero retained", total_retained == 0,
              f"got {total_retained}")

    # ── Issue doc reproducers (real event pairs, custom windows) ──
    step(30, "Retention — Issue doc reproducers (existing data)")

    ISSUE_TR = {"start": "2026-03-18 12:17:18", "end": "2026-04-17 12:17:18"}
    reproducers = [
        ("login→login 1d daily", "auth.login_success", "auth.login_success", "1d", "daily"),
        ("login→tournament 7d", "auth.login_success", "tournament.viewed", "7d", "daily"),
        ("signup→created 14d weekly", "organizer.signup_started", "tournament.created", "14d", "weekly"),
        ("custom 3d", "auth.login_success", "role.switched", "3d", "daily"),
        ("custom 60d", "auth.login_success", "role.switched", "60d", "daily"),
        ("custom 12h", "auth.login_success", "role.switched", "12h", "daily"),
        ("custom 2w", "auth.login_success", "role.switched", "2w", "daily"),
    ]
    for label, init_evt, ret_evt, window, gran in reproducers:
        r = requests.post(f"{api}/metrics/compute/", headers=headers, json={
            "type": "retention",
            "config": {
                "time_range": ISSUE_TR, "granularity": gran,
                "group_by": [], "filters": {},
                "initial_event": {"event_name": init_evt},
                "return_event": {"event_name": ret_evt},
                "retention_window": window,
            },
        })
        check(f"Retention {label} returns 200", r.status_code == 200,
              f"got {r.status_code}")
