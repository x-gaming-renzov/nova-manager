"""Steps 1-4: Auth — register, login, token refresh, get current user."""

import sys
import requests
from scripts.integration.helpers import RUN_ID, step, check

TEST_EMAIL = f"smoke_{RUN_ID}@example.com"
TEST_PASSWORD = "smoke_test_2026!"
TEST_NAME = "Smoke Test User"
TEST_COMPANY = f"SmokeTestCo_{RUN_ID}"


def run(base: str, state: dict):
    api = f"{base}/api/v1"

    # ── Register ─────────────────────────────────────────
    step(1, "Auth — Register New User")

    r = requests.post(f"{api}/auth/register", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD,
        "name": TEST_NAME,
        "company": TEST_COMPANY,
    })
    if not check("Register returns 200", r.status_code == 200,
                  f"got {r.status_code}: {r.text[:200]}"):
        print("Cannot register. Aborting.")
        sys.exit(1)

    body = r.json()
    check("Register returns access_token", "access_token" in body, "missing")
    check("Register returns refresh_token", "refresh_token" in body, "missing")
    check("Register returns expires_in", "expires_in" in body, "missing")

    state["access_token"] = body["access_token"]
    state["refresh_token"] = body["refresh_token"]
    state["headers"] = {"Authorization": f"Bearer {body['access_token']}"}

    # ── Login ────────────────────────────────────────────
    step(2, "Auth — Login")

    r = requests.post(f"{api}/auth/login", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD,
    })
    check("Login returns 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        login_body = r.json()
        check("Login returns access_token", "access_token" in login_body, "missing")
        check("Login returns refresh_token", "refresh_token" in login_body, "missing")
        state["access_token"] = login_body["access_token"]
        state["refresh_token"] = login_body["refresh_token"]
        state["headers"] = {"Authorization": f"Bearer {login_body['access_token']}"}

    # Wrong password
    r = requests.post(f"{api}/auth/login", json={
        "email": TEST_EMAIL,
        "password": "wrong_password_123",
    })
    check("Wrong password returns 400", r.status_code == 400, f"got {r.status_code}")

    # Duplicate register
    r = requests.post(f"{api}/auth/register", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD,
        "name": TEST_NAME,
        "company": TEST_COMPANY,
    })
    check("Duplicate register returns 400", r.status_code == 400, f"got {r.status_code}")

    # ── Token Refresh ────────────────────────────────────
    step(3, "Auth — Token Refresh")

    r = requests.post(f"{api}/auth/refresh",
        headers=state["headers"],
        json={"refresh_token": state["refresh_token"]},
    )
    check("Token refresh returns 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        refresh_body = r.json()
        check("Refresh returns new access_token", "access_token" in refresh_body, "missing")
        state["access_token"] = refresh_body["access_token"]
        state["headers"] = {"Authorization": f"Bearer {refresh_body['access_token']}"}

    r = requests.post(f"{api}/auth/refresh",
        headers=state["headers"],
        json={"refresh_token": "invalid_token_xyz"},
    )
    check("Refresh with bad token fails", r.status_code in (401, 403), f"got {r.status_code}")

    # ── Get Current User ─────────────────────────────────
    step(4, "Auth — Get Current User")

    r = requests.get(f"{api}/auth/me", headers=state["headers"])
    check("GET /me returns 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        me = r.json()
        check("GET /me returns correct email", me.get("email") == TEST_EMAIL, f"got {me.get('email')}")
        check("GET /me returns correct name", me.get("name") == TEST_NAME, f"got {me.get('name')}")
        check("GET /me returns role", "role" in me, "missing role")

    r = requests.get(f"{api}/auth/me")
    check("GET /me without auth returns 403", r.status_code == 403, f"got {r.status_code}")
