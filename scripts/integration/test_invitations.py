"""Step 18: Invitations — send, list, validate (email integration)."""

import requests
from scripts.integration.helpers import RUN_ID, step, check


def run(base: str, state: dict):
    api = f"{base}/api/v1"
    headers = state["headers"]

    step(18, "Invitations — Send, List, Validate (email)")

    invite_email = f"invite_{RUN_ID}@example.com"

    # Send invitation (triggers Brevo email)
    r = requests.post(f"{api}/invitations/invite", headers=headers, json={
        "email": invite_email,
        "role": "member",
    })
    check("Send invitation returns 200", r.status_code == 200,
          f"got {r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        body = r.json()
        check("Invitation has id", "id" in body, "missing id")
        check("Invitation email matches", body.get("email") == invite_email,
              f"got {body.get('email')}")
        check("Invitation status is pending", body.get("status") == "pending",
              f"got {body.get('status')}")
        check("Invitation has expires_at", "expires_at" in body, "missing expires_at")
        check("Invitation has invited_by_name", "invited_by_name" in body, "missing")
        check("Invitation has organisation_name", "organisation_name" in body, "missing")

    # List invitations
    r = requests.get(f"{api}/invitations/invitations?status=pending", headers=headers)
    check("List invitations returns 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        invitations = r.json()
        check("Pending invitations >= 1", len(invitations) >= 1, f"got {len(invitations)}")
        # Find our invitation
        our_inv = [i for i in invitations if i.get("email") == invite_email]
        check("Our invitation in list", len(our_inv) == 1,
              f"found {len(our_inv)} matching")

    # Duplicate invitation should fail
    r = requests.post(f"{api}/invitations/invite", headers=headers, json={
        "email": invite_email,
        "role": "member",
    })
    check("Duplicate invitation returns 400", r.status_code == 400, f"got {r.status_code}")
