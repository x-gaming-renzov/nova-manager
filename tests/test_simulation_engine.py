"""Unit tests for the simulation engine.

Tests the pure compute_simulation() function against the Excel v2 sheet
(Battlin GTM KPI Simulator) as source of truth. No DB or ClickHouse needed.
"""

import pytest

from nova_manager.components.simulations.engine import compute_simulation


# ── Excel v2 assumptions (James v2 sheet) ─────────────────────────

V2_ASSUMPTIONS = {
    "time_range": {"start_month": "2026-07", "end_month": "2026-12"},
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
        "2026-09": {
            "new_tos_per_month": 200,
            "to_retention_rate": 0.87,
            "tournaments_per_to_per_month": 15,
            "grimm_bot_tournaments": 0,
            "mau": 49371,
            "dau_mau_ratio": 0.17,
            "pct_inorganic_players": 0.1,
            "player_cpi": 0.9,
            "avg_teams_per_tournament": 16,
            "avg_players_per_team": 4,
            "fill_rate": 0.8,
            "milestone_reward_per_to_inr": 4500,
            "leaderboard_pool_inr": 240000,
            "grand_prize_amortized_inr": 300000,
            "initial_credit_per_to_inr": 2000,
            "initial_credit_new_users_inr": 400000,
            "r1_achievement_rate": 0.5,
            "r2_achievement_rate": 0.2,
            "usd_inr_rate": 90,
            "marketing_budgets": {
                "social_channel": 5000,
                "college_activation": 15000,
                "kol_influencer": 15000,
                "seo_aso": 2000,
                "pr_media": 2000,
            },
            "ad_revenue": {
                "static_impressions_per_dau": 15,
                "interstitial_impressions_per_dau": 2,
                "video_impressions_per_dau": 1,
                "ecpm_static": 0.18,
                "ecpm_interstitial": 0.35,
                "ecpm_video": 1.80,
                "ad_fill_rate": 0.6,
            },
            "sponsorship": {"active_deals": 1, "avg_deal_value": 5000},
            "webshop_revenue": 0,
        },
        "2026-10": {
            "new_tos_per_month": 200,
            "to_retention_rate": 0.87,
            "tournaments_per_to_per_month": 12,
            "grimm_bot_tournaments": 50,
            "mau": 120000,
            "dau_mau_ratio": 0.18,
            "pct_inorganic_players": 0.2,
            "player_cpi": 0.8,
            "avg_teams_per_tournament": 16,
            "avg_players_per_team": 4,
            "fill_rate": 0.85,
            "milestone_reward_per_to_inr": 2000,
            "leaderboard_pool_inr": 360000,
            "grand_prize_amortized_inr": 300000,
            "initial_credit_per_to_inr": 2000,
            "initial_credit_new_users_inr": 400000,
            "r1_achievement_rate": 0.4,
            "r2_achievement_rate": 0.1,
            "usd_inr_rate": 90,
            "marketing_budgets": {
                "social_channel": 5000,
                "college_activation": 15000,
                "seo_aso": 2000,
                "bgmi_giveaways": 5000,
                "marquee_tourney": 20000,
            },
            "ad_revenue": {
                "static_impressions_per_dau": 18,
                "interstitial_impressions_per_dau": 2,
                "video_impressions_per_dau": 1,
                "ecpm_static": 0.18,
                "ecpm_interstitial": 0.35,
                "ecpm_video": 1.80,
                "ad_fill_rate": 0.65,
            },
            "sponsorship": {"active_deals": 2, "avg_deal_value": 5000},
            "webshop_revenue": 0,
        },
        "2026-11": {
            "new_tos_per_month": 200,
            "to_retention_rate": 0.87,
            "tournaments_per_to_per_month": 10,
            "grimm_bot_tournaments": 50,
            "mau": 220000,
            "dau_mau_ratio": 0.19,
            "pct_inorganic_players": 0.3,
            "player_cpi": 0.7,
            "avg_teams_per_tournament": 16,
            "avg_players_per_team": 4,
            "fill_rate": 0.9,
            "milestone_reward_per_to_inr": 2000,
            "leaderboard_pool_inr": 480000,
            "grand_prize_amortized_inr": 300000,
            "initial_credit_per_to_inr": 2000,
            "initial_credit_new_users_inr": 400000,
            "r1_achievement_rate": 0.5,
            "r2_achievement_rate": 0.2,
            "usd_inr_rate": 90,
            "marketing_budgets": {
                "social_channel": 5000,
                "college_activation": 15000,
                "kol_influencer": 15000,
                "seo_aso": 2000,
                "bgmi_giveaways": 3000,
                "pr_media": 2000,
            },
            "ad_revenue": {
                "static_impressions_per_dau": 20,
                "interstitial_impressions_per_dau": 3,
                "video_impressions_per_dau": 2,
                "ecpm_static": 0.20,
                "ecpm_interstitial": 0.40,
                "ecpm_video": 2.00,
                "ad_fill_rate": 0.7,
            },
            "sponsorship": {"active_deals": 3, "avg_deal_value": 5000},
            "webshop_revenue": 500,
        },
        "2026-12": {
            "new_tos_per_month": 200,
            "to_retention_rate": 0.87,
            "tournaments_per_to_per_month": 10,
            "grimm_bot_tournaments": 50,
            "mau": 330000,
            "dau_mau_ratio": 0.20,
            "pct_inorganic_players": 0.3,
            "player_cpi": 0.6,
            "avg_teams_per_tournament": 16,
            "avg_players_per_team": 4,
            "fill_rate": 0.8,
            "milestone_reward_per_to_inr": 2000,
            "leaderboard_pool_inr": 600000,
            "grand_prize_amortized_inr": 300000,
            "initial_credit_per_to_inr": 2000,
            "initial_credit_new_users_inr": 400000,
            "r1_achievement_rate": 0.5,
            "r2_achievement_rate": 0.2,
            "usd_inr_rate": 90,
            "marketing_budgets": {
                "social_channel": 5000,
                "seo_aso": 2000,
            },
            "ad_revenue": {
                "static_impressions_per_dau": 20,
                "interstitial_impressions_per_dau": 3,
                "video_impressions_per_dau": 2,
                "ecpm_static": 0.20,
                "ecpm_interstitial": 0.40,
                "ecpm_video": 2.00,
                "ad_fill_rate": 0.7,
            },
            "sponsorship": {"active_deals": 5, "avg_deal_value": 5000},
            "webshop_revenue": 2000,
        },
    },
}

# Expected values from the Excel v2 sheet (source of truth)
EXCEL_EXPECTED = {
    "active_tos": [250, 417.5, 563.225, 690.00575, 800.3050025, 896.265352175],
    "total_tournaments": [2500, 5010, 8448.375, 8330.069, 8053.0500250, 9012.65352175],
    "mau": [12000, 25000, 49371, 120000, 220000, 330000],
    "dau": [1800, 4000, 8393.07, 21600, 41800, 66000],
    "inorganic_players": [0, 0, 4937.1, 24000, 66000, 99000],
    "fill_rate": [0.7, 0.75, 0.8, 0.85, 0.9, 0.8],
    "to_incentive_l1": [9722.222, 18555.556, 28161.25, 15333.461, 17784.556, 19917.008],
    "to_incentive_l2": [2666.667, 2666.667, 2666.667, 4000, 5333.333, 6666.667],
    "to_incentive_l3": [3333.333, 3333.333, 3333.333, 3333.333, 3333.333, 3333.333],
    "to_incentive_total": [15722.222, 24555.556, 34161.25, 22666.794, 26451.222, 29917.008],
    "sponsored_credits": [5555.556, 17201.389, 23531.514, 25527.953, 31565.892, 34817.881],
    "supply_ua": [21277.778, 41756.944, 57692.764, 48194.748, 58017.114, 64734.889],
    "demand_ua": [0, 0, 4443.39, 19200, 46200, 59400],
    "ad_revenue": [49, 238, 786, 2418, 8076, 12751],
    "sponsorship_revenue": [0, 0, 5000, 10000, 15000, 25000],
    "webshop_revenue": [0, 0, 0, 0, 500, 2000],
    "total_revenue": [49, 238, 5786, 12418, 23576, 39751],
}

MONTHS = ["2026-07", "2026-08", "2026-09", "2026-10", "2026-11", "2026-12"]


def _get_values(rows: list[dict], metric_name: str, dimension: str = "") -> list[float]:
    """Extract monthly values for a metric from engine output."""
    filtered = [
        r for r in rows
        if r["metric_name"] == metric_name and r["dimension"] == dimension
    ]
    by_period = {r["period_start"][:7]: r["value"] for r in filtered}
    return [by_period.get(m, 0) for m in MONTHS]


def _assert_close(computed: list[float], expected: list[float], label: str, tol: float = 0.01):
    """Assert computed values match expected within tolerance."""
    assert len(computed) == len(expected), f"{label}: length mismatch {len(computed)} vs {len(expected)}"
    for i, (c, e) in enumerate(zip(computed, expected)):
        if e == 0:
            assert abs(c) < 0.01, f"{label} [{MONTHS[i]}]: got {c}, expected ~0"
        else:
            rel_err = abs(c - e) / abs(e)
            assert rel_err < tol, f"{label} [{MONTHS[i]}]: {c} vs {e} (err={rel_err:.4%})"


# ── Tests ─────────────────────────────────────────────────────────


class TestSupplyCascade:
    def setup_method(self):
        self.rows = compute_simulation(V2_ASSUMPTIONS)

    def test_active_tos(self):
        _assert_close(
            _get_values(self.rows, "active_tos"),
            EXCEL_EXPECTED["active_tos"],
            "active_tos",
        )

    def test_total_tournaments(self):
        _assert_close(
            _get_values(self.rows, "total_tournaments"),
            EXCEL_EXPECTED["total_tournaments"],
            "total_tournaments",
        )

    def test_to_incentive_layers(self):
        _assert_close(
            _get_values(self.rows, "to_incentive_l1", "milestones"),
            EXCEL_EXPECTED["to_incentive_l1"],
            "to_incentive_l1",
        )
        _assert_close(
            _get_values(self.rows, "to_incentive_l2", "leaderboard"),
            EXCEL_EXPECTED["to_incentive_l2"],
            "to_incentive_l2",
        )
        _assert_close(
            _get_values(self.rows, "to_incentive_l3", "grand_prize"),
            EXCEL_EXPECTED["to_incentive_l3"],
            "to_incentive_l3",
        )
        _assert_close(
            _get_values(self.rows, "to_incentive_total"),
            EXCEL_EXPECTED["to_incentive_total"],
            "to_incentive_total",
        )

    def test_sponsored_credits(self):
        _assert_close(
            _get_values(self.rows, "sponsored_credits"),
            EXCEL_EXPECTED["sponsored_credits"],
            "sponsored_credits",
        )

    def test_supply_ua(self):
        _assert_close(
            _get_values(self.rows, "supply_ua"),
            EXCEL_EXPECTED["supply_ua"],
            "supply_ua",
        )


class TestDemand:
    def setup_method(self):
        self.rows = compute_simulation(V2_ASSUMPTIONS)

    def test_mau(self):
        _assert_close(
            _get_values(self.rows, "mau"),
            EXCEL_EXPECTED["mau"],
            "mau",
        )

    def test_dau(self):
        _assert_close(
            _get_values(self.rows, "dau"),
            EXCEL_EXPECTED["dau"],
            "dau",
        )

    def test_inorganic_players(self):
        _assert_close(
            _get_values(self.rows, "inorganic_players"),
            EXCEL_EXPECTED["inorganic_players"],
            "inorganic_players",
        )

    def test_demand_ua(self):
        _assert_close(
            _get_values(self.rows, "demand_ua"),
            EXCEL_EXPECTED["demand_ua"],
            "demand_ua",
        )


class TestRevenue:
    def setup_method(self):
        self.rows = compute_simulation(V2_ASSUMPTIONS)

    def test_ad_revenue(self):
        _assert_close(
            _get_values(self.rows, "ad_revenue"),
            EXCEL_EXPECTED["ad_revenue"],
            "ad_revenue",
        )

    def test_sponsorship_revenue(self):
        _assert_close(
            _get_values(self.rows, "sponsorship_revenue"),
            EXCEL_EXPECTED["sponsorship_revenue"],
            "sponsorship_revenue",
        )

    def test_webshop_revenue(self):
        _assert_close(
            _get_values(self.rows, "webshop_revenue"),
            EXCEL_EXPECTED["webshop_revenue"],
            "webshop_revenue",
        )

    def test_total_revenue(self):
        _assert_close(
            _get_values(self.rows, "total_revenue"),
            EXCEL_EXPECTED["total_revenue"],
            "total_revenue",
        )


class TestOutputFormat:
    def setup_method(self):
        self.rows = compute_simulation(V2_ASSUMPTIONS)

    def test_row_keys(self):
        for row in self.rows:
            assert "metric_name" in row
            assert "dimension" in row
            assert "value" in row
            assert "period_start" in row
            assert "currency" in row

    def test_period_format(self):
        for row in self.rows:
            assert row["period_start"].endswith("T00:00:00Z")

    def test_nonempty(self):
        assert len(self.rows) > 100  # ~20 metrics × 6 months + channel breakdowns


class TestEdgeCases:
    def test_empty_months(self):
        result = compute_simulation({
            "time_range": {"start_month": "2026-07", "end_month": "2026-06"},
            "seed_values": {},
            "months": {},
        })
        assert result == []

    def test_single_month(self):
        assumptions = {
            "time_range": {"start_month": "2026-07", "end_month": "2026-07"},
            "seed_values": {"active_tos": 0},
            "months": {
                "2026-07": {
                    "new_tos_per_month": 100,
                    "to_retention_rate": 0.87,
                    "tournaments_per_to_per_month": 10,
                    "mau": 5000,
                    "dau_mau_ratio": 0.15,
                    "fill_rate": 0.7,
                    "avg_teams_per_tournament": 16,
                    "avg_players_per_team": 4,
                    "usd_inr_rate": 90,
                    "marketing_budgets": {},
                    "ad_revenue": {},
                    "sponsorship": {},
                    "webshop_revenue": 0,
                },
            },
        }
        rows = compute_simulation(assumptions)
        tos = _get_values(rows, "active_tos")
        assert tos[0] == 100  # seed=0, first month = 0*0.87 + 100 = 100

    def test_zero_tournaments_no_division_error(self):
        assumptions = {
            "time_range": {"start_month": "2026-07", "end_month": "2026-07"},
            "seed_values": {"active_tos": 0},
            "months": {
                "2026-07": {
                    "new_tos_per_month": 0,
                    "to_retention_rate": 0,
                    "tournaments_per_to_per_month": 0,
                    "mau": 0,
                    "dau_mau_ratio": 0,
                    "fill_rate": 0,
                    "avg_teams_per_tournament": 0,
                    "avg_players_per_team": 0,
                    "usd_inr_rate": 90,
                    "marketing_budgets": {},
                    "ad_revenue": {},
                    "sponsorship": {},
                    "webshop_revenue": 0,
                },
            },
        }
        rows = compute_simulation(assumptions)
        avg_p = [r for r in rows if r["metric_name"] == "avg_participants"]
        assert avg_p[0]["value"] == 0  # no division by zero
