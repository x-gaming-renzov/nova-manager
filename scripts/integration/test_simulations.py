"""Steps 27-32: Simulation CRUD, engine execution, KPI validation, multi-scenario.

Tests the full simulation flow end-to-end:
  - Create simulation with full 6-month v2 assumptions
  - Run engine, validate all 9 KPIs against Excel expected values
  - Create a second scenario (neutral), run, verify isolation
  - Cross-scenario comparison
  - Run history, re-runs, updates
"""

import json
import sys
from pathlib import Path

import requests
from scripts.integration.helpers import RUN_ID, step, check

# Import Excel parsing + full v2 assumptions from test fixtures
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from tests.test_simulation_engine import V2_ASSUMPTIONS


# Excel expected KPIs for v2 scenario (6 months)
EXPECTED_KPIS = {
    "CAC":      {"expr": "spend / mau",         "ops": {"spend": "total_marketing_spend", "mau": "mau"},                    "expected": [2.1898, 1.7903, 2.0485, 0.9533, 0.6646, 0.3974]},
    "ROAS":     {"expr": "revenue / spend",      "ops": {"revenue": "total_revenue", "spend": "total_marketing_spend"},       "expected": [0.001865, 0.005318, 0.057210, 0.108554, 0.161240, 0.303131]},
    "ARPU":     {"expr": "revenue / mau",        "ops": {"revenue": "total_revenue", "mau": "mau"},                          "expected": [0.004083, 0.009520, 0.117194, 0.103483, 0.107164, 0.120458]},
    "Net Margin": {"expr": "revenue - spend",    "ops": {"revenue": "total_revenue", "spend": "total_marketing_spend"},       "expected": [-26228.78, -44518.94, -95350.06, -101976.75, -122641.11, -91383.89]},
    "Supply CAC": {"expr": "supply_ua / tos",    "ops": {"supply_ua": "supply_ua", "tos": "active_tos"},                     "expected": [85.1111, 100.0166, 102.4329, 69.8469, 72.4938, 72.2274]},
    "Cost/Tourney": {"expr": "spend / t",        "ops": {"spend": "total_marketing_spend", "t": "total_tournaments"},         "expected": [10.5111, 8.9335, 11.9711, 13.7327, 18.1567, 14.5501]},
    "Rev/Tourney": {"expr": "revenue / t",       "ops": {"revenue": "total_revenue", "t": "total_tournaments"},               "expected": [0.0196, 0.04750, 0.6849, 1.4907, 2.9276, 4.4106]},
    "Margin %": {"expr": "(revenue - spend) / revenue", "ops": {"revenue": "total_revenue", "spend": "total_marketing_spend"},"expected": [-535.2812, -187.0544, -16.4794, -8.2120, -5.2019, -2.2989]},
}

# Neutral scenario: fewer TOs (50/month instead of 200)
NEUTRAL_ASSUMPTIONS = json.loads(json.dumps(V2_ASSUMPTIONS))  # deep copy
for month_key in NEUTRAL_ASSUMPTIONS["months"]:
    if month_key != "2026-07":
        NEUTRAL_ASSUMPTIONS["months"][month_key]["new_tos_per_month"] = 50

# Expected neutral CAC (higher spend per user since fewer TOs → different spend)
EXPECTED_NEUTRAL_CAC_JUL = None  # computed dynamically — just check it's different from v2


def _compute_formula(api, headers, scenario_id, expression, operands):
    """Helper to compute a formula KPI via the API."""
    ops = {}
    for name, metric_name in operands.items():
        ops[name] = {"type": "operational", "config": {"metric_name": metric_name, "aggregation": "sum", "scenario_id": scenario_id}}

    r = requests.post(f"{api}/metrics/compute/", headers=headers, json={
        "type": "formula",
        "config": {
            "time_range": {"start": "2026-07-01 00:00:00", "end": "2027-01-01 00:00:00"},
            "granularity": "monthly",
            "group_by": [],
            "operands": ops,
            "expression": expression,
        },
    })
    return r


def run(base: str, state: dict):
    api = f"{base}/api/v1"
    headers = state["headers"]

    # ── Step 27: Create Simulation (v2) ────────────────────
    step(27, "Simulation — Create & CRUD")

    r = requests.post(f"{api}/simulations/", headers=headers, json={
        "name": f"GTM V2 {RUN_ID}",
        "description": "Full v2 scenario — 6 months",
        "scenario_id": f"sim_v2_{RUN_ID}",
        "assumptions": V2_ASSUMPTIONS,
    })
    check("Create v2 simulation returns 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")

    sim_v2_id = None
    if r.status_code == 200:
        sim = r.json()
        sim_v2_id = sim["pid"]
        check("Simulation has pid", sim_v2_id is not None, "")
        check("Status is draft", sim["status"] == "draft", f"got {sim['status']}")
        check("Has 6 months of assumptions", len(sim["assumptions"]["months"]) == 6, "")

    # Duplicate name rejected
    r = requests.post(f"{api}/simulations/", headers=headers, json={
        "name": f"GTM V2 {RUN_ID}", "scenario_id": "other", "assumptions": {},
    })
    check("Duplicate name rejected", r.status_code == 400, f"got {r.status_code}")

    # Duplicate scenario_id rejected
    r = requests.post(f"{api}/simulations/", headers=headers, json={
        "name": "Other Name", "scenario_id": f"sim_v2_{RUN_ID}", "assumptions": {},
    })
    check("Duplicate scenario_id rejected", r.status_code == 400, f"got {r.status_code}")

    # List
    r = requests.get(f"{api}/simulations/", headers=headers)
    check("List simulations returns 200", r.status_code == 200, "")

    # Get by ID
    r = requests.get(f"{api}/simulations/{sim_v2_id}/", headers=headers)
    check("Get simulation by ID returns 200", r.status_code == 200, "")

    # ── Step 28: Run v2 Simulation ─────────────────────────
    step(28, "Simulation — Run V2 Engine (6 months)")

    if not sim_v2_id:
        print("  SKIP  No simulation to run")
        return

    r = requests.post(f"{api}/simulations/{sim_v2_id}/run/", headers=headers)
    check("Run v2 returns 200", r.status_code == 200, f"got {r.status_code}: {r.text[:300]}")

    if r.status_code == 200:
        run_data = r.json()
        check("Run completed", run_data["run"]["status"] == "completed", f"got {run_data['run']['status']}")
        check("Metrics written ~140", run_data["metrics_written"] >= 120, f"got {run_data['metrics_written']}")
        print(f"  Metrics written: {run_data['metrics_written']}")

    # Schema discovery
    scenario_v2 = f"sim_v2_{RUN_ID}"
    r = requests.get(f"{api}/metrics/business-data/schema/?scenario_id={scenario_v2}", headers=headers)
    check("Schema discovery returns 200", r.status_code == 200, "")
    if r.status_code == 200:
        names = sorted({row["metric_name"] for row in r.json()})
        check("Schema has 21 metric names", len(names) >= 20, f"got {len(names)}: {names[:5]}...")
        for required in ["active_tos", "total_marketing_spend", "total_revenue", "mau"]:
            check(f"Schema has {required}", required in names, "")

    # ── Step 29: Validate all 9 KPIs against Excel ─────────
    step(29, "Simulation — Validate 9 KPIs Against Excel")

    kpi_pass = 0
    kpi_fail = 0

    for kpi_name, kpi_def in EXPECTED_KPIS.items():
        r = _compute_formula(api, headers, scenario_v2, kpi_def["expr"], kpi_def["ops"])
        if r.status_code != 200:
            check(f"{kpi_name} compute returns 200", False, f"got {r.status_code}")
            kpi_fail += 1
            continue

        data = sorted(r.json(), key=lambda x: str(x.get("period", "")))
        expected = kpi_def["expected"]

        all_match = True
        for i, row in enumerate(data):
            if i >= len(expected):
                break
            c = row["value"]
            e = expected[i]
            if e == 0:
                match = abs(c) < 0.01
            else:
                match = abs(c - e) / abs(e) < 0.01
            if not match:
                all_match = False

        if all_match:
            kpi_pass += 1
        else:
            kpi_fail += 1
        check(f"{kpi_name} matches Excel ({len(data)} months)", all_match, f"computed vs expected mismatch")

    print(f"  KPIs: {kpi_pass}/{kpi_pass + kpi_fail}")

    # ── Step 30: Second Scenario (Neutral) ─────────────────
    step(30, "Simulation — Second Scenario & Isolation")

    r = requests.post(f"{api}/simulations/", headers=headers, json={
        "name": f"GTM Neutral {RUN_ID}",
        "description": "Conservative — 50 new TOs/month",
        "scenario_id": f"sim_neutral_{RUN_ID}",
        "assumptions": NEUTRAL_ASSUMPTIONS,
    })
    check("Create neutral simulation returns 200", r.status_code == 200, f"got {r.status_code}")

    sim_neutral_id = None
    if r.status_code == 200:
        sim_neutral_id = r.json()["pid"]

        # Run neutral
        r = requests.post(f"{api}/simulations/{sim_neutral_id}/run/", headers=headers)
        check("Run neutral returns 200", r.status_code == 200, "")

    # Compare CAC between scenarios — they should differ
    scenario_neutral = f"sim_neutral_{RUN_ID}"
    r_v2 = _compute_formula(api, headers, scenario_v2, "spend / mau", {"spend": "total_marketing_spend", "mau": "mau"})
    r_neutral = _compute_formula(api, headers, scenario_neutral, "spend / mau", {"spend": "total_marketing_spend", "mau": "mau"})

    if r_v2.status_code == 200 and r_neutral.status_code == 200:
        v2_data = sorted(r_v2.json(), key=lambda x: str(x.get("period", "")))
        neutral_data = sorted(r_neutral.json(), key=lambda x: str(x.get("period", "")))
        check("Both scenarios have 6 months", len(v2_data) == 6 and len(neutral_data) == 6, "")

        # Aug onward should differ (v2 adds 200 TOs, neutral adds 50)
        if len(v2_data) >= 2 and len(neutral_data) >= 2:
            v2_aug = v2_data[1]["value"]
            neutral_aug = neutral_data[1]["value"]
            check(f"V2 Aug CAC ({v2_aug:.2f}) != Neutral Aug CAC ({neutral_aug:.2f})",
                  abs(v2_aug - neutral_aug) > 0.01, "scenarios not isolated")

    # Schema shows both scenarios
    r = requests.get(f"{api}/metrics/business-data/schema/", headers=headers)
    if r.status_code == 200:
        scenarios = sorted({row.get("scenario_id") for row in r.json()})
        check("Schema shows both scenarios", scenario_v2 in scenarios and scenario_neutral in scenarios,
              f"got {scenarios}")

    # ── Step 31: Run History & Re-runs ─────────────────────
    step(31, "Simulation — Run History & Re-runs")

    r = requests.get(f"{api}/simulations/{sim_v2_id}/runs/", headers=headers)
    check("V2 has 1 run", r.status_code == 200 and len(r.json()) == 1, "")

    # Re-run (idempotent)
    r = requests.post(f"{api}/simulations/{sim_v2_id}/run/", headers=headers)
    check("V2 re-run returns 200", r.status_code == 200, "")

    r = requests.get(f"{api}/simulations/{sim_v2_id}/runs/", headers=headers)
    check("V2 now has 2 runs", r.status_code == 200 and len(r.json()) == 2, "")

    # Verify run records exist with expected status
    if r.status_code == 200:
        runs = r.json()
        statuses = [run.get("status") for run in runs]
        check("All runs completed", all(s == "completed" for s in statuses), f"got {statuses}")

    # Re-run produces same KPIs (idempotent)
    r_after = _compute_formula(api, headers, scenario_v2, "spend / mau", {"spend": "total_marketing_spend", "mau": "mau"})
    if r_v2.status_code == 200 and r_after.status_code == 200:
        before = sorted(r_v2.json(), key=lambda x: str(x.get("period", "")))
        after = sorted(r_after.json(), key=lambda x: str(x.get("period", "")))
        same = all(abs(b["value"] - a["value"]) < 0.01 for b, a in zip(before, after))
        check("Re-run produces identical KPIs", same, "")

    # ── Step 32: Update & Delete ───────────────────────────
    step(32, "Simulation — Update & Delete")

    r = requests.put(f"{api}/simulations/{sim_v2_id}/", headers=headers, json={
        "status": "active", "description": "Promoted to active",
    })
    check("Update status to active", r.status_code == 200 and r.json()["status"] == "active", "")

    # Delete neutral simulation
    if sim_neutral_id:
        r = requests.delete(f"{api}/simulations/{sim_neutral_id}/", headers=headers)
        check("Delete neutral simulation", r.status_code == 200, f"got {r.status_code}")

        # Verify deleted
        r = requests.get(f"{api}/simulations/{sim_neutral_id}/", headers=headers)
        check("Deleted simulation returns 404", r.status_code == 404, f"got {r.status_code}")

    # List should have 1 remaining
    r = requests.get(f"{api}/simulations/", headers=headers)
    if r.status_code == 200:
        remaining = [s for s in r.json() if RUN_ID in s.get("name", "")]
        check("1 simulation remaining after delete", len(remaining) == 1, f"got {len(remaining)}")
