"""Steps 27-30: Simulation CRUD, engine execution, KPI validation.

Tests the full simulation flow:
  - Create a simulation with assumptions
  - Run the engine (writes derived metrics to ClickHouse)
  - Validate computed KPIs against expected values
  - Verify run history
"""

import json
import requests
from scripts.integration.helpers import RUN_ID, step, check


# Minimal v2-like assumptions for 2 months (Jul+Aug) to keep test fast
TEST_ASSUMPTIONS = {
    "time_range": {"start_month": "2026-07", "end_month": "2026-08"},
    "seed_values": {"active_tos": 0},
    "months": {
        "2026-07": {
            "new_tos_per_month": 250,
            "to_retention_rate": 0.87,
            "tournaments_per_to_per_month": 10,
            "grimm_bot_tournaments": 0,
            "mau": 12000,
            "dau_mau_ratio": 0.15,
            "pct_inorganic_players": 0.0,
            "player_cpi": 0.2,
            "avg_teams_per_tournament": 16,
            "avg_players_per_team": 4,
            "fill_rate": 0.7,
            "milestone_reward_per_to_inr": 3500,
            "leaderboard_pool_inr": 240000,
            "grand_prize_amortized_inr": 300000,
            "initial_credit_per_to_inr": 2000,
            "initial_credit_new_users_inr": 0,
            "r1_achievement_rate": 0,
            "r2_achievement_rate": 0,
            "usd_inr_rate": 90,
            "marketing_budgets": {"bgmi_giveaways": 5000},
            "ad_revenue": {
                "static_impressions_per_dau": 10,
                "interstitial_impressions_per_dau": 1,
                "video_impressions_per_dau": 0,
                "ecpm_static": 0.15,
                "ecpm_interstitial": 0.30,
                "ecpm_video": 1.50,
                "ad_fill_rate": 0.5,
            },
            "sponsorship": {"active_deals": 0, "avg_deal_value": 0},
            "webshop_revenue": 0,
        },
        "2026-08": {
            "new_tos_per_month": 200,
            "to_retention_rate": 0.87,
            "tournaments_per_to_per_month": 12,
            "grimm_bot_tournaments": 0,
            "mau": 25000,
            "dau_mau_ratio": 0.16,
            "pct_inorganic_players": 0.0,
            "player_cpi": 0.5,
            "avg_teams_per_tournament": 16,
            "avg_players_per_team": 4,
            "fill_rate": 0.75,
            "milestone_reward_per_to_inr": 4000,
            "leaderboard_pool_inr": 240000,
            "grand_prize_amortized_inr": 300000,
            "initial_credit_per_to_inr": 2000,
            "initial_credit_new_users_inr": 400000,
            "r1_achievement_rate": 0.4,
            "r2_achievement_rate": 0.1,
            "usd_inr_rate": 90,
            "marketing_budgets": {"bgmi_giveaways": 3000},
            "ad_revenue": {
                "static_impressions_per_dau": 12,
                "interstitial_impressions_per_dau": 1,
                "video_impressions_per_dau": 1,
                "ecpm_static": 0.15,
                "ecpm_interstitial": 0.30,
                "ecpm_video": 1.50,
                "ad_fill_rate": 0.55,
            },
            "sponsorship": {"active_deals": 0, "avg_deal_value": 0},
            "webshop_revenue": 0,
        },
    },
}

# Expected values from Excel v2 for Jul+Aug
EXPECTED_CAC_JUL = 2.1898
EXPECTED_CAC_AUG = 1.7903


def run(base: str, state: dict):
    api = f"{base}/api/v1"
    headers = state["headers"]

    # ── Create Simulation ──────────────────────────────────
    step(27, "Simulation — Create")

    r = requests.post(f"{api}/simulations/", headers=headers, json={
        "name": f"Integration Test Sim {RUN_ID}",
        "description": "Integration test simulation",
        "scenario_id": f"integ_sim_{RUN_ID}",
        "assumptions": TEST_ASSUMPTIONS,
    })
    check("Create simulation returns 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")

    sim_id = None
    if r.status_code == 200:
        sim = r.json()
        sim_id = sim.get("pid")
        check("Simulation has pid", sim_id is not None, f"got {sim}")
        check("Simulation status is draft", sim.get("status") == "draft", f"got {sim.get('status')}")
        check("Simulation has assumptions", "months" in sim.get("assumptions", {}), f"got {sim.get('assumptions', {}).keys()}")
        print(f"  Simulation: {sim_id}")

    # List simulations
    r = requests.get(f"{api}/simulations/", headers=headers)
    check("List simulations returns 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        sims = r.json()
        check("At least 1 simulation listed", len(sims) >= 1, f"got {len(sims)}")

    # Get simulation by ID
    if sim_id:
        r = requests.get(f"{api}/simulations/{sim_id}/", headers=headers)
        check("Get simulation by ID returns 200", r.status_code == 200, f"got {r.status_code}")

    # ── Run Simulation ─────────────────────────────────────
    step(28, "Simulation — Run Engine")

    if not sim_id:
        print("  SKIP  No simulation to run")
        return

    r = requests.post(f"{api}/simulations/{sim_id}/run/", headers=headers)
    check("Run simulation returns 200", r.status_code == 200, f"got {r.status_code}: {r.text[:300]}")

    if r.status_code == 200:
        run_data = r.json()
        run_status = run_data.get("run", {}).get("status")
        metrics_written = run_data.get("metrics_written", 0)
        check("Run status is completed", run_status == "completed", f"got {run_status}")
        check("Metrics written > 0", metrics_written > 0, f"got {metrics_written}")
        print(f"  Metrics written: {metrics_written}")

    # ── Validate KPIs ──────────────────────────────────────
    step(29, "Simulation — Validate KPIs via /metrics/compute/")

    scenario_id = f"integ_sim_{RUN_ID}"

    # CAC = total_marketing_spend / mau
    r = requests.post(f"{api}/metrics/compute/", headers=headers, json={
        "type": "formula",
        "config": {
            "time_range": {"start": "2026-07-01 00:00:00", "end": "2026-09-01 00:00:00"},
            "granularity": "monthly",
            "group_by": [],
            "operands": {
                "spend": {"type": "operational", "config": {"metric_name": "total_marketing_spend", "aggregation": "sum", "scenario_id": scenario_id}},
                "mau": {"type": "operational", "config": {"metric_name": "mau", "aggregation": "sum", "scenario_id": scenario_id}},
            },
            "expression": "spend / mau",
        },
    })
    check("CAC compute returns 200", r.status_code == 200, f"got {r.status_code}: {r.text[:300]}")

    if r.status_code == 200:
        data = r.json()
        check("CAC has 2 months", len(data) == 2, f"got {len(data)} rows: {data}")
        if len(data) >= 2:
            sorted_data = sorted(data, key=lambda x: str(x.get("period", "")))
            jul_cac = sorted_data[0].get("value", 0)
            aug_cac = sorted_data[1].get("value", 0)
            jul_match = abs(jul_cac - EXPECTED_CAC_JUL) / EXPECTED_CAC_JUL < 0.01
            aug_match = abs(aug_cac - EXPECTED_CAC_AUG) / EXPECTED_CAC_AUG < 0.01
            check(f"Jul CAC matches Excel ({jul_cac:.4f} vs {EXPECTED_CAC_JUL})", jul_match, f"err={abs(jul_cac - EXPECTED_CAC_JUL):.4f}")
            check(f"Aug CAC matches Excel ({aug_cac:.4f} vs {EXPECTED_CAC_AUG})", aug_match, f"err={abs(aug_cac - EXPECTED_CAC_AUG):.4f}")

    # Schema discovery — verify scenario data is in ClickHouse
    r = requests.get(f"{api}/metrics/business-data/schema/?scenario_id={scenario_id}", headers=headers)
    check("Schema discovery for simulation scenario returns 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        schema = r.json()
        metric_names = {row["metric_name"] for row in schema}
        check("Schema has active_tos", "active_tos" in metric_names, f"got {metric_names}")
        check("Schema has total_marketing_spend", "total_marketing_spend" in metric_names, f"got {metric_names}")
        print(f"  Schema: {len(metric_names)} metrics for {scenario_id}")

    # ── Run History ────────────────────────────────────────
    step(30, "Simulation — Run History & Update")

    r = requests.get(f"{api}/simulations/{sim_id}/runs/", headers=headers)
    check("List runs returns 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        runs = r.json()
        check("Has 1 run", len(runs) == 1, f"got {len(runs)}")
        if runs:
            check("Run status is completed", runs[0].get("status") == "completed", f"got {runs[0].get('status')}")

    # Re-run (idempotent)
    r = requests.post(f"{api}/simulations/{sim_id}/run/", headers=headers)
    check("Re-run returns 200", r.status_code == 200, f"got {r.status_code}")

    r = requests.get(f"{api}/simulations/{sim_id}/runs/", headers=headers)
    if r.status_code == 200:
        runs = r.json()
        check("Now has 2 runs", len(runs) == 2, f"got {len(runs)}")

    # Update simulation
    r = requests.put(f"{api}/simulations/{sim_id}/", headers=headers, json={
        "description": "Updated description",
        "status": "active",
    })
    check("Update simulation returns 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        sim = r.json()
        check("Status updated to active", sim.get("status") == "active", f"got {sim.get('status')}")
