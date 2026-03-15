"""Steps 8, 13: SDK credentials & SDK user creation."""

import requests
from scripts.integration.helpers import RUN_ID, step, check


def run(base: str, state: dict):
    api = f"{base}/api/v1"
    headers = state["headers"]

    # ── SDK Credentials ──────────────────────────────────
    step(8, "SDK — Get Credentials")

    r = requests.get(f"{api}/auth/sdk-credentials", headers=headers)
    check("Get SDK credentials returns 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        sdk_data = r.json()
        check("Response has sdk_api_key", "sdk_api_key" in sdk_data, "missing")
        check("Response has backend_url", "backend_url" in sdk_data, "missing")
        sdk_api_key = sdk_data.get("sdk_api_key", "")
        check("SDK key starts with nova_sk_", sdk_api_key.startswith("nova_sk_"),
              f"got {sdk_api_key[:20]}")
        state["sdk_api_key"] = sdk_api_key

    state["sdk_headers"] = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {state.get('sdk_api_key', '')}",
    }

    # ── Create SDK Users ─────────────────────────────────
    step(13, "SDK — Create Users with Profiles")

    sdk_headers = state["sdk_headers"]

    r = requests.post(f"{api}/users/create-user/", headers=sdk_headers, json={
        "user_id": f"smoke_user_{RUN_ID}",
        "user_profile": {
            "name": "Smoke Tester",
            "level": "10",
            "country": "US",
        },
    })
    check("Create SDK user returns 200", r.status_code in (200, 201), f"got {r.status_code}")
    if r.status_code == 200:
        check("Response has nova_user_id", "nova_user_id" in r.json(), "missing")

    r = requests.post(f"{api}/users/create-user/", headers=sdk_headers, json={
        "user_id": f"smoke_user2_{RUN_ID}",
        "user_profile": {
            "name": "Smoke Tester 2",
            "level": "3",
            "country": "GB",
        },
    })
    check("Create second SDK user", r.status_code in (200, 201), f"got {r.status_code}")
