"""Steps 5-7: App creation, listing, switching, org users."""

import requests
from scripts.integration.helpers import RUN_ID, step, check

TEST_APP_NAME = f"Smoke App {RUN_ID}"


def run(base: str, state: dict):
    api = f"{base}/api/v1"
    headers = state["headers"]

    # ── Create App ───────────────────────────────────────
    step(5, "App — Create (ClickHouse provisioning)")

    r = requests.post(f"{api}/auth/apps", headers=headers, json={
        "name": TEST_APP_NAME,
        "description": f"Integration test app — run {RUN_ID}",
    })
    check("Create app returns 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        body = r.json()
        check("Create app returns app object", "app" in body, "missing app")
        check("Create app returns access_token", "access_token" in body, "missing token")
        check("App name matches", body["app"]["name"] == TEST_APP_NAME,
              f"got {body['app'].get('name')}")
        state["app_id"] = body["app"]["id"]
        state["access_token"] = body["access_token"]
        state["headers"] = {"Authorization": f"Bearer {body['access_token']}"}
        print(f"  App ID: {state['app_id']}")

    headers = state["headers"]

    # ── List & Switch App ────────────────────────────────
    step(6, "App — List & Switch")

    r = requests.get(f"{api}/auth/apps", headers=headers)
    check("List apps returns 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        apps = r.json()
        check("At least 1 app exists", len(apps) >= 1, f"got {len(apps)} apps")

    r = requests.post(f"{api}/auth/switch-app", headers=headers, json={
        "app_id": state["app_id"],
    })
    check("Switch app returns 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        state["access_token"] = r.json()["access_token"]
        state["headers"] = {"Authorization": f"Bearer {state['access_token']}"}

    # ── List Org Users ───────────────────────────────────
    step(7, "Auth — List Org Users")

    headers = state["headers"]
    r = requests.get(f"{api}/auth/users", headers=headers)
    check("List org users returns 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        users = r.json()
        check("At least 1 org user", len(users) >= 1, f"got {len(users)}")
        from scripts.integration.test_auth import TEST_EMAIL
        own_user = [u for u in users if u["email"] == TEST_EMAIL]
        check("Current user in org users list", len(own_user) == 1, "not found")
        if own_user:
            check("User role is owner", own_user[0]["role"] == "owner",
                  f"got {own_user[0].get('role')}")
