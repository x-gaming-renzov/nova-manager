"""Steps 9-12: Feature flags, segments, experiences, personalisations CRUD."""

import requests
from scripts.integration.helpers import RUN_ID, step, check


def run(base: str, state: dict):
    api = f"{base}/api/v1"
    headers = state["headers"]
    sdk_headers = state["sdk_headers"]

    # ── Feature Flags ────────────────────────────────────
    step(9, "Feature Flags — List & Sync")

    r = requests.get(f"{api}/feature-flags/", headers=headers)
    check("List feature flags returns 200", r.status_code == 200, f"got {r.status_code}")

    r = requests.post(f"{api}/feature-flags/sync-nova-objects/", headers=sdk_headers, json={
        "objects": {
            f"smoke_flag_{RUN_ID}": {
                "type": "feature_flag",
                "keys": {"enabled": {"type": "boolean", "description": "on/off", "default": True}},
            },
        },
        "experiences": {},
    })
    check("Sync feature flags returns 200", r.status_code == 200,
          f"got {r.status_code}: {r.text[:200]}")

    r = requests.get(f"{api}/feature-flags/", headers=headers)
    if r.status_code == 200:
        flags = r.json()
        smoke_flags = [f for f in flags if f"smoke_flag_{RUN_ID}" in f.get("name", "")]
        check("Synced flag in list", len(smoke_flags) >= 1,
              f"found {len(smoke_flags)} matching flags")

    # ── Segments ─────────────────────────────────────────
    step(10, "Segments — CRUD")

    r = requests.post(f"{api}/segments/", headers=headers, json={
        "name": f"smoke_segment_{RUN_ID}",
        "description": "Smoke test segment",
        "rule_config": {
            "operator": "AND",
            "conditions": [
                {"field": "country", "operator": "equals", "value": "US",
                 "source": "user_profile"},
            ],
        },
    })
    check("Create segment returns 200", r.status_code == 200,
          f"got {r.status_code}: {r.text[:200]}")
    segment_id = r.json().get("pid") if r.status_code == 200 else None

    r = requests.get(f"{api}/segments/", headers=headers)
    check("List segments returns 200", r.status_code == 200, f"got {r.status_code}")

    if segment_id:
        r = requests.get(f"{api}/segments/{segment_id}/", headers=headers)
        check("Get segment by ID returns 200", r.status_code == 200, f"got {r.status_code}")

        r = requests.put(f"{api}/segments/{segment_id}/", headers=headers, json={
            "name": f"smoke_segment_{RUN_ID}_v2",
            "description": "Updated smoke test segment",
            "rule_config": {
                "operator": "AND",
                "conditions": [
                    {"field": "level", "operator": "greater_than", "value": "5",
                     "source": "user_profile"},
                ],
            },
        })
        check("Update segment returns 200", r.status_code == 200,
              f"got {r.status_code}: {r.text[:200]}")

    # ── Experiences ──────────────────────────────────────
    step(11, "Experiences — List & Get")

    r = requests.get(f"{api}/experiences/", headers=headers)
    check("List experiences returns 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        experiences = r.json()
        print(f"  Found {len(experiences)} experiences")
        if experiences:
            exp_id = experiences[0]["pid"]
            r = requests.get(f"{api}/experiences/{exp_id}/", headers=headers)
            check("Get experience by ID returns 200", r.status_code == 200,
                  f"got {r.status_code}")
            r = requests.get(f"{api}/experiences/{exp_id}/features/", headers=headers)
            check("Get experience features returns 200", r.status_code == 200,
                  f"got {r.status_code}")

    # ── Personalisations ─────────────────────────────────
    step(12, "Personalisations — List")

    r = requests.get(f"{api}/personalisations/", headers=headers)
    check("List personalisations returns 200", r.status_code == 200, f"got {r.status_code}")
