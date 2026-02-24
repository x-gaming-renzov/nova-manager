#!/usr/bin/env python3
"""
Nova Manager - Full Flow Test
Registers user, creates app, gets SDK key, tracks events, verifies ClickHouse.
Handles already-existing users/apps gracefully.
"""

import json
import subprocess
import sys
import time

import requests

BASE_URL = "http://localhost:8000/api/v1"
CLICKHOUSE_CONTAINER = "nova-manager-clickhouse-1"

# Test data
TEST_EMAIL = "test@test.com"
TEST_PASSWORD = "test1234"
TEST_NAME = "Test User"
TEST_COMPANY = "TestCo"
TEST_APP_NAME = "My App"


def pp(data):
    """Pretty print JSON."""
    print(json.dumps(data, indent=2, default=str))


def clickhouse_query(query: str) -> str:
    """Run a query inside the ClickHouse container."""
    result = subprocess.run(
        ["docker", "exec", CLICKHOUSE_CONTAINER, "clickhouse-client", "--query", query],
        capture_output=True, text=True,
    )
    return result.stdout.strip()


def step(num, title):
    print(f"\n{'─' * 50}")
    print(f"  Step {num}: {title}")
    print(f"{'─' * 50}")


# ──────────────────────────────────────────────────────
#  Step 1: Register or Login
# ──────────────────────────────────────────────────────
step(1, "Register / Login")

r = requests.post(f"{BASE_URL}/auth/register", json={
    "email": TEST_EMAIL,
    "password": TEST_PASSWORD,
    "name": TEST_NAME,
    "company": TEST_COMPANY,
})

if r.status_code == 200:
    print("Registered new user.")
    access_token = r.json()["access_token"]
elif r.status_code == 400 and "already exists" in r.json().get("detail", ""):
    print("User already exists. Logging in...")
    r = requests.post(f"{BASE_URL}/auth/login", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD,
    })
    r.raise_for_status()
    access_token = r.json()["access_token"]
    print("Logged in.")
else:
    print(f"ERROR: {r.status_code}")
    pp(r.json())
    sys.exit(1)

print(f"Token: {access_token[:40]}...")
headers = {"Authorization": f"Bearer {access_token}"}


# ──────────────────────────────────────────────────────
#  Step 2: Create or reuse app
# ──────────────────────────────────────────────────────
step(2, "Create / Reuse App")

# Check if apps already exist
r = requests.get(f"{BASE_URL}/auth/apps", headers=headers)

if r.status_code == 200 and r.json():
    apps = r.json()
    app = apps[0]
    print(f"App already exists: {app['name']} (id: {app['id']})")

    # Switch to this app to get app-scoped token
    r = requests.post(f"{BASE_URL}/auth/switch-app", headers=headers, json={
        "app_id": str(app["id"]),
    })
    r.raise_for_status()
    access_token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}
    print("Switched to existing app.")
else:
    # Create new app (provisions ClickHouse database + 4 tables)
    r = requests.post(f"{BASE_URL}/auth/apps", headers=headers, json={
        "name": TEST_APP_NAME,
        "description": "Test app for flow verification",
    })
    r.raise_for_status()
    data = r.json()
    access_token = data["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}
    print(f"Created app: {data['app']['name']} (id: {data['app']['id']})")

print(f"Token (app-scoped): {access_token[:40]}...")


# ──────────────────────────────────────────────────────
#  Step 3: Get SDK credentials
# ──────────────────────────────────────────────────────
step(3, "Get SDK Credentials")

r = requests.get(f"{BASE_URL}/auth/sdk-credentials", headers=headers)
r.raise_for_status()
sdk_data = r.json()
sdk_api_key = sdk_data["sdk_api_key"]
print(f"SDK API Key: {sdk_api_key[:40]}...")
print(f"Backend URL: {sdk_data['backend_url']}")

sdk_headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {sdk_api_key}",
}


# ──────────────────────────────────────────────────────
#  Step 4: Create a user with profile
# ──────────────────────────────────────────────────────
step(4, "Create User with Profile")

r = requests.post(f"{BASE_URL}/users/create-user/", headers=sdk_headers, json={
    "user_id": "user_test_001",
    "user_profile": {
        "name": "John Doe",
        "level": "5",
        "country": "US",
    },
})

if r.status_code == 200:
    pp(r.json())
else:
    print(f"Status: {r.status_code}")
    pp(r.json())


# ──────────────────────────────────────────────────────
#  Step 5: Track events
# ──────────────────────────────────────────────────────
step(5, "Track Events")

events = [
    {
        "user_id": "user_test_001",
        "event_name": "button_click",
        "event_data": {"button_id": "signup", "page": "home"},
        "timestamp": "2026-02-23T12:00:00Z",
    },
    {
        "user_id": "user_test_001",
        "event_name": "page_view",
        "event_data": {"page": "/dashboard", "referrer": "/home"},
        "timestamp": "2026-02-23T12:01:00Z",
    },
    {
        "user_id": "user_test_001",
        "event_name": "purchase",
        "event_data": {"item": "sword", "amount": "9.99", "currency": "USD"},
        "timestamp": "2026-02-23T12:02:00Z",
    },
]

for event in events:
    r = requests.post(f"{BASE_URL}/metrics/track-event/", headers=sdk_headers, json=event)
    status = "OK" if r.status_code == 200 else f"FAIL ({r.status_code})"
    print(f"  {event['event_name']:20s} -> {status}")


# ──────────────────────────────────────────────────────
#  Step 6: Wait for worker
# ──────────────────────────────────────────────────────
step(6, "Waiting for worker to process jobs...")

for i in range(5, 0, -1):
    print(f"  {i}s...", end=" ", flush=True)
    time.sleep(1)
print("done!")


# ──────────────────────────────────────────────────────
#  Step 7: Verify ClickHouse
# ──────────────────────────────────────────────────────
step(7, "Verify ClickHouse Data")

databases = clickhouse_query("SHOW DATABASES")
print(f"\nDatabases:\n{databases}\n")

# Find org_* database
org_dbs = [db for db in databases.splitlines() if db.startswith("org_")]

if not org_dbs:
    print("WARNING: No org_* database found. Worker may still be processing.")
    print("Try running this script again in a few seconds.")
    sys.exit(0)

db_name = org_dbs[0]
print(f"Using database: {db_name}\n")

# Show tables
tables = clickhouse_query(f"SHOW TABLES FROM `{db_name}`")
print(f"Tables:\n{tables}\n")

# Row counts
counts = clickhouse_query(
    f"SELECT 'raw_events' AS tbl, count() AS cnt FROM `{db_name}`.raw_events "
    f"UNION ALL SELECT 'event_props', count() FROM `{db_name}`.event_props "
    f"UNION ALL SELECT 'user_profile_props', count() FROM `{db_name}`.user_profile_props "
    f"UNION ALL SELECT 'user_experience', count() FROM `{db_name}`.user_experience "
    f"FORMAT PrettyCompact"
)
print(f"Row counts:\n{counts}\n")

# Sample data
print("─── raw_events (sample) ───")
print(clickhouse_query(f"SELECT event_id, user_id, event_name, client_ts FROM `{db_name}`.raw_events LIMIT 10 FORMAT PrettyCompact"))

print("\n─── event_props (sample) ───")
print(clickhouse_query(f"SELECT event_id, event_name, key, value FROM `{db_name}`.event_props LIMIT 10 FORMAT PrettyCompact"))

print("\n─── user_profile_props (sample) ───")
print(clickhouse_query(f"SELECT * FROM `{db_name}`.user_profile_props LIMIT 10 FORMAT PrettyCompact"))

# ──────────────────────────────────────────────────────
#  Step 8: Test Metrics Compute API
# ──────────────────────────────────────────────────────
step(8, "Test Metrics Compute API (dashboard JWT)")

# 8a. Count all events for 'button_click'
print("\n── 8a: COUNT button_click events ──")
r = requests.post(f"{BASE_URL}/metrics/compute/", headers=headers, json={
    "type": "count",
    "config": {
        "event_name": "button_click",
        "distinct": False,
        "time_range": {"start": "2026-01-01T00:00:00", "end": "2026-12-31T23:59:59"},
        "granularity": "daily",
        "group_by": [],
        "filters": {},
    },
})
if r.status_code == 200:
    print(f"  Status: OK")
    pp(r.json())
else:
    print(f"  FAIL ({r.status_code})")
    pp(r.json())

# 8b. Count distinct users across ALL events
print("\n── 8b: COUNT DISTINCT users (all events) ──")
r = requests.post(f"{BASE_URL}/metrics/compute/", headers=headers, json={
    "type": "count",
    "config": {
        "event_name": "page_view",
        "distinct": True,
        "time_range": {"start": "2026-01-01T00:00:00", "end": "2026-12-31T23:59:59"},
        "granularity": "monthly",
        "group_by": [],
        "filters": {},
    },
})
if r.status_code == 200:
    print(f"  Status: OK")
    pp(r.json())
else:
    print(f"  FAIL ({r.status_code})")
    pp(r.json())

# 8c. Aggregation: SUM of purchase amounts
print("\n── 8c: SUM purchase amounts ──")
r = requests.post(f"{BASE_URL}/metrics/compute/", headers=headers, json={
    "type": "aggregation",
    "config": {
        "event_name": "purchase",
        "property": "amount",
        "aggregation": "sum",
        "time_range": {"start": "2026-01-01T00:00:00", "end": "2026-12-31T23:59:59"},
        "granularity": "daily",
        "group_by": [],
        "filters": {},
    },
})
if r.status_code == 200:
    print(f"  Status: OK")
    pp(r.json())
else:
    print(f"  FAIL ({r.status_code})")
    pp(r.json())

# 8d. Count with GROUP BY event property
print("\n── 8d: COUNT button_click GROUP BY page ──")
r = requests.post(f"{BASE_URL}/metrics/compute/", headers=headers, json={
    "type": "count",
    "config": {
        "event_name": "button_click",
        "distinct": False,
        "time_range": {"start": "2026-01-01T00:00:00", "end": "2026-12-31T23:59:59"},
        "granularity": "daily",
        "group_by": [{"key": "page", "source": "event_properties"}],
        "filters": {},
    },
})
if r.status_code == 200:
    print(f"  Status: OK")
    pp(r.json())
else:
    print(f"  FAIL ({r.status_code})")
    pp(r.json())

# 8e. Ratio: purchase / page_view conversion rate
print("\n── 8e: RATIO purchase / page_view ──")
r = requests.post(f"{BASE_URL}/metrics/compute/", headers=headers, json={
    "type": "ratio",
    "config": {
        "numerator": {"event_name": "purchase"},
        "denominator": {"event_name": "page_view"},
        "time_range": {"start": "2026-01-01T00:00:00", "end": "2026-12-31T23:59:59"},
        "granularity": "daily",
        "group_by": [],
        "filters": {},
    },
})
if r.status_code == 200:
    print(f"  Status: OK")
    pp(r.json())
else:
    print(f"  FAIL ({r.status_code})")
    pp(r.json())


# ──────────────────────────────────────────────────────
#  Step 9: Test Events Schema & Profile Keys APIs
# ──────────────────────────────────────────────────────
step(9, "Events Schema & User Profile Keys")

print("\n── 9a: GET events-schema ──")
r = requests.get(f"{BASE_URL}/metrics/events-schema/", headers=headers)
if r.status_code == 200:
    schemas = r.json()
    print(f"  Found {len(schemas)} event schemas:")
    for s in schemas:
        props = list(s.get("event_schema", {}).get("properties", {}).keys())
        print(f"    • {s['event_name']}: properties={props}")
else:
    print(f"  FAIL ({r.status_code})")
    pp(r.json())

print("\n── 9b: GET user-profile-keys ──")
r = requests.get(f"{BASE_URL}/metrics/user-profile-keys/", headers=headers)
if r.status_code == 200:
    keys = r.json()
    print(f"  Found {len(keys)} profile keys:")
    for k in keys:
        print(f"    • {k['key']} ({k['type']})")
else:
    print(f"  FAIL ({r.status_code})")
    pp(r.json())


print(f"\n{'=' * 50}")
print("  Test flow complete!")
print(f"{'=' * 50}")
