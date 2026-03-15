"""Step 19: Auth guards — verify unauthorized access is blocked."""

import requests
from scripts.integration.helpers import step, check


def run(base: str, _state: dict):
    api = f"{base}/api/v1"
    bad_headers = {"Authorization": "Bearer invalid_token_xyz"}

    step(19, "Auth Guards — Unauthorized Access")

    r = requests.get(f"{api}/auth/apps", headers=bad_headers)
    check("Bad token on /apps → 401/403", r.status_code in (401, 403), f"got {r.status_code}")

    r = requests.get(f"{api}/feature-flags/", headers=bad_headers)
    check("Bad token on /feature-flags → 401/403", r.status_code in (401, 403),
          f"got {r.status_code}")

    r = requests.post(f"{api}/metrics/track-event/", headers=bad_headers, json={
        "user_id": "attacker", "event_name": "hack", "event_data": {},
    })
    check("Bad SDK key on /track-event → 401/403", r.status_code in (401, 403),
          f"got {r.status_code}")

    r = requests.get(f"{api}/segments/")
    check("No auth on /segments → 403", r.status_code == 403, f"got {r.status_code}")

    r = requests.post(f"{api}/invitations/invite", json={"email": "x@x.com", "role": "member"})
    check("No auth on /invite → 403", r.status_code == 403, f"got {r.status_code}")
