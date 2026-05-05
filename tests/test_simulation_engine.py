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


class TestTemporalCascade:
    """Test that month-over-month dependencies compute correctly."""

    def test_to_retention_accumulates(self):
        """Active TOs: Jul=250, Aug=250*0.87+200=417.5, Sep=417.5*0.87+200=563.225."""
        rows = compute_simulation(V2_ASSUMPTIONS)
        tos = _get_values(rows, "active_tos")
        assert tos[0] == 250  # first month seed
        assert abs(tos[1] - (250 * 0.87 + 200)) < 0.01  # 417.5
        assert abs(tos[2] - (417.5 * 0.87 + 200)) < 0.01  # 563.225

    def test_six_month_cascade_precision(self):
        """Verify the full 6-month cascade maintains precision through to Dec."""
        rows = compute_simulation(V2_ASSUMPTIONS)
        tos = _get_values(rows, "active_tos")
        # Manually compute the chain
        chain = [250]
        for m in range(5):
            chain.append(chain[-1] * 0.87 + 200)
        for i in range(6):
            assert abs(tos[i] - chain[i]) < 0.001, f"Month {i}: {tos[i]} vs {chain[i]}"

    def test_grimm_bot_only_from_october(self):
        """GRIMM bot tournaments added from Oct (index 3) onward."""
        rows = compute_simulation(V2_ASSUMPTIONS)
        tournaments = _get_values(rows, "total_tournaments")
        tos = _get_values(rows, "active_tos")
        # Jul-Sep: no grimm bot
        assert abs(tournaments[0] - tos[0] * 10) < 0.01
        assert abs(tournaments[1] - tos[1] * 12) < 0.01
        assert abs(tournaments[2] - tos[2] * 15) < 0.01
        # Oct-Dec: +50 grimm bot
        assert abs(tournaments[3] - (tos[3] * 12 + 50)) < 0.01
        assert abs(tournaments[4] - (tos[4] * 10 + 50)) < 0.01
        assert abs(tournaments[5] - (tos[5] * 10 + 50)) < 0.01

    def test_different_retention_rates(self):
        """Different retention rates produce different cascades."""
        base = {
            "time_range": {"start_month": "2026-07", "end_month": "2026-09"},
            "seed_values": {"active_tos": 0},
            "months": {},
        }
        month_template = {
            "new_tos_per_month": 100, "tournaments_per_to_per_month": 10,
            "mau": 1000, "dau_mau_ratio": 0.1, "fill_rate": 0.5,
            "avg_teams_per_tournament": 16, "avg_players_per_team": 4,
            "usd_inr_rate": 90, "marketing_budgets": {},
            "ad_revenue": {}, "sponsorship": {}, "webshop_revenue": 0,
        }

        # High retention
        high = dict(base, months={
            "2026-07": {**month_template, "to_retention_rate": 0.95},
            "2026-08": {**month_template, "to_retention_rate": 0.95},
            "2026-09": {**month_template, "to_retention_rate": 0.95},
        })
        # Low retention
        low = dict(base, months={
            "2026-07": {**month_template, "to_retention_rate": 0.50},
            "2026-08": {**month_template, "to_retention_rate": 0.50},
            "2026-09": {**month_template, "to_retention_rate": 0.50},
        })

        high_tos = _get_values(compute_simulation(high), "active_tos")
        low_tos = _get_values(compute_simulation(low), "active_tos")

        assert high_tos[0] == low_tos[0] == 100  # same first month
        assert high_tos[1] > low_tos[1]  # high retention → more TOs
        assert high_tos[2] > low_tos[2]  # gap widens

    def test_seed_value_nonzero(self):
        """Non-zero seed value carries retention into first month."""
        assumptions = {
            "time_range": {"start_month": "2026-07", "end_month": "2026-08"},
            "seed_values": {"active_tos": 500},
            "months": {
                "2026-07": {
                    "new_tos_per_month": 100, "to_retention_rate": 0.90,
                    "tournaments_per_to_per_month": 10, "mau": 1000,
                    "dau_mau_ratio": 0.1, "fill_rate": 0.5,
                    "avg_teams_per_tournament": 16, "avg_players_per_team": 4,
                    "usd_inr_rate": 90, "marketing_budgets": {},
                    "ad_revenue": {}, "sponsorship": {}, "webshop_revenue": 0,
                },
                "2026-08": {
                    "new_tos_per_month": 100, "to_retention_rate": 0.90,
                    "tournaments_per_to_per_month": 10, "mau": 1000,
                    "dau_mau_ratio": 0.1, "fill_rate": 0.5,
                    "avg_teams_per_tournament": 16, "avg_players_per_team": 4,
                    "usd_inr_rate": 90, "marketing_budgets": {},
                    "ad_revenue": {}, "sponsorship": {}, "webshop_revenue": 0,
                },
            },
        }
        rows = compute_simulation(assumptions)
        tos = _get_values(rows, "active_tos")
        assert abs(tos[0] - (500 * 0.90 + 100)) < 0.01  # 550
        assert abs(tos[1] - (550 * 0.90 + 100)) < 0.01  # 595


class TestIndividualComputations:
    """Test each derived metric formula in isolation."""

    def setup_method(self):
        self.rows = compute_simulation(V2_ASSUMPTIONS)

    def test_player_slots_formula(self):
        """total_player_slots = tournaments * teams * players * fill_rate."""
        slots = _get_values(self.rows, "total_player_slots")
        tournaments = _get_values(self.rows, "total_tournaments")
        fills = [0.7, 0.75, 0.8, 0.85, 0.9, 0.8]
        for i in range(6):
            expected = tournaments[i] * 16 * 4 * fills[i]
            assert abs(slots[i] - expected) < 1, f"Month {i}: {slots[i]} vs {expected}"

    def test_avg_participants_formula(self):
        """avg_participants = total_player_slots / total_tournaments."""
        avg = _get_values(self.rows, "avg_participants")
        slots = _get_values(self.rows, "total_player_slots")
        tournaments = _get_values(self.rows, "total_tournaments")
        for i in range(6):
            expected = slots[i] / tournaments[i] if tournaments[i] > 0 else 0
            assert abs(avg[i] - expected) < 0.01

    def test_dau_formula(self):
        """dau = mau * dau_mau_ratio."""
        dau = _get_values(self.rows, "dau")
        mau = _get_values(self.rows, "mau")
        ratios = [0.15, 0.16, 0.17, 0.18, 0.19, 0.20]
        for i in range(6):
            assert abs(dau[i] - mau[i] * ratios[i]) < 1

    def test_inorganic_players_formula(self):
        """inorganic_players = mau * pct_inorganic."""
        inorg = _get_values(self.rows, "inorganic_players")
        mau = _get_values(self.rows, "mau")
        pcts = [0.0, 0.0, 0.1, 0.2, 0.3, 0.3]
        for i in range(6):
            assert abs(inorg[i] - mau[i] * pcts[i]) < 1

    def test_demand_ua_formula(self):
        """demand_ua = inorganic_players * player_cpi."""
        demand = _get_values(self.rows, "demand_ua")
        inorg = _get_values(self.rows, "inorganic_players")
        cpis = [0.2, 0.5, 0.9, 0.8, 0.7, 0.6]
        for i in range(6):
            assert abs(demand[i] - inorg[i] * cpis[i]) < 1

    def test_to_incentive_l1_formula(self):
        """L1 = active_tos * milestone_reward / usd_inr."""
        l1 = _get_values(self.rows, "to_incentive_l1", "milestones")
        tos = _get_values(self.rows, "active_tos")
        rewards = [3500, 4000, 4500, 2000, 2000, 2000]
        for i in range(6):
            expected = tos[i] * rewards[i] / 90
            assert abs(l1[i] - expected) < 0.01, f"Month {i}: {l1[i]} vs {expected}"

    def test_to_incentive_l2_fixed_pool(self):
        """L2 = leaderboard_pool / usd_inr (pool varies by month)."""
        l2 = _get_values(self.rows, "to_incentive_l2", "leaderboard")
        pools = [240000, 240000, 240000, 360000, 480000, 600000]
        for i in range(6):
            assert abs(l2[i] - pools[i] / 90) < 0.01

    def test_to_incentive_l3_fixed(self):
        """L3 = grand_prize_amortized / usd_inr (constant 300000)."""
        l3 = _get_values(self.rows, "to_incentive_l3", "grand_prize")
        for i in range(6):
            assert abs(l3[i] - 300000 / 90) < 0.01

    def test_to_incentive_total_is_sum(self):
        """to_incentive_total = L1 + L2 + L3."""
        total = _get_values(self.rows, "to_incentive_total")
        l1 = _get_values(self.rows, "to_incentive_l1", "milestones")
        l2 = _get_values(self.rows, "to_incentive_l2", "leaderboard")
        l3 = _get_values(self.rows, "to_incentive_l3", "grand_prize")
        for i in range(6):
            assert abs(total[i] - (l1[i] + l2[i] + l3[i])) < 0.01

    def test_sponsored_credits_initial_plus_refill(self):
        """sponsored_credits = (initial_credit + refill) / usd_inr."""
        sc = _get_values(self.rows, "sponsored_credits")
        tos = _get_values(self.rows, "active_tos")
        # Jul: initial only (no refill), no new user credits
        initial_jul = tos[0] * 2000  # 250 * 2000 = 500000
        assert abs(sc[0] - initial_jul / 90) < 0.01
        # Aug: initial + new user credits + refill
        initial_aug = tos[1] * 2000 + 400000  # active_tos*credit + new_users
        refill_aug = (0.4 + 0.1) * 1500 * tos[1]  # r1+r2 * 1500 * active_tos
        assert abs(sc[1] - (initial_aug + refill_aug) / 90) < 0.01

    def test_supply_ua_is_incentives_plus_credits(self):
        """supply_ua = to_incentive_total + sponsored_credits."""
        supply = _get_values(self.rows, "supply_ua")
        incentive = _get_values(self.rows, "to_incentive_total")
        credits = _get_values(self.rows, "sponsored_credits")
        for i in range(6):
            assert abs(supply[i] - (incentive[i] + credits[i])) < 0.01

    def test_ad_revenue_formula(self):
        """ad_revenue = round(dau * sum(imp*ecpm) * fill_rate / 1000 * 30)."""
        ad = _get_values(self.rows, "ad_revenue")
        # Jul: dau=1800, static=10*0.15, inter=1*0.3, video=0, fill=0.5
        daily = 1800 * (10 * 0.15 + 1 * 0.3 + 0) / 1000 * 0.5
        assert ad[0] == round(daily * 30)  # 49

    def test_total_revenue_is_sum(self):
        """total_revenue = ad + sponsorship + webshop."""
        total = _get_values(self.rows, "total_revenue")
        ad = _get_values(self.rows, "ad_revenue")
        sp = _get_values(self.rows, "sponsorship_revenue")
        ws = _get_values(self.rows, "webshop_revenue")
        for i in range(6):
            assert abs(total[i] - (ad[i] + sp[i] + ws[i])) < 0.01

    def test_total_marketing_spend_composition(self):
        """total_marketing_spend = supply_ua + demand_ua + channel_budgets."""
        total = _get_values(self.rows, "total_marketing_spend")
        supply = _get_values(self.rows, "supply_ua")
        demand = _get_values(self.rows, "demand_ua")
        # Channel budgets from assumptions
        budgets_by_month = [5000, 3000, 39000, 47000, 42000, 7000]
        for i in range(6):
            expected = supply[i] + demand[i] + budgets_by_month[i]
            assert abs(total[i] - expected) < 1, f"Month {i}: {total[i]} vs {expected}"


class TestMarketingChannelBreakdown:
    """Test that marketing_spend rows are emitted per channel with dimension."""

    def setup_method(self):
        self.rows = compute_simulation(V2_ASSUMPTIONS)

    def test_channel_rows_have_dimension(self):
        spend_rows = [r for r in self.rows if r["metric_name"] == "marketing_spend"]
        for row in spend_rows:
            assert row["dimension"] != "", f"marketing_spend row without dimension: {row}"

    def test_jul_only_bgmi_giveaways(self):
        """July has only bgmi_giveaways = 5000."""
        jul_spend = [r for r in self.rows
                     if r["metric_name"] == "marketing_spend" and r["period_start"][:7] == "2026-07"]
        assert len(jul_spend) == 1
        assert jul_spend[0]["dimension"] == "bgmi_giveaways"
        assert jul_spend[0]["value"] == 5000

    def test_sep_has_five_channels(self):
        """September has 5 marketing channels."""
        sep_spend = [r for r in self.rows
                     if r["metric_name"] == "marketing_spend" and r["period_start"][:7] == "2026-09"]
        channels = {r["dimension"] for r in sep_spend}
        assert channels == {"social_channel", "college_activation", "kol_influencer", "seo_aso", "pr_media"}

    def test_zero_budget_channels_omitted(self):
        """Channels with zero budget should not emit rows."""
        for row in self.rows:
            if row["metric_name"] == "marketing_spend":
                assert row["value"] > 0


class TestCurrencyConversion:
    """Test INR to USD conversion via usd_inr_rate."""

    def test_different_exchange_rate(self):
        """Changing usd_inr_rate changes USD outputs proportionally."""
        assumptions_90 = {
            "time_range": {"start_month": "2026-07", "end_month": "2026-07"},
            "seed_values": {"active_tos": 0},
            "months": {"2026-07": {
                "new_tos_per_month": 100, "to_retention_rate": 0.87,
                "tournaments_per_to_per_month": 10, "mau": 1000,
                "dau_mau_ratio": 0.1, "fill_rate": 0.5,
                "avg_teams_per_tournament": 16, "avg_players_per_team": 4,
                "milestone_reward_per_to_inr": 3000,
                "leaderboard_pool_inr": 200000,
                "grand_prize_amortized_inr": 300000,
                "initial_credit_per_to_inr": 2000,
                "usd_inr_rate": 90,
                "marketing_budgets": {}, "ad_revenue": {},
                "sponsorship": {}, "webshop_revenue": 0,
            }},
        }
        assumptions_80 = {
            "time_range": {"start_month": "2026-07", "end_month": "2026-07"},
            "seed_values": {"active_tos": 0},
            "months": {"2026-07": {
                **assumptions_90["months"]["2026-07"],
                "usd_inr_rate": 80,
            }},
        }

        rows_90 = compute_simulation(assumptions_90)
        rows_80 = compute_simulation(assumptions_80)

        l1_90 = [r["value"] for r in rows_90 if r["metric_name"] == "to_incentive_l1"][0]
        l1_80 = [r["value"] for r in rows_80 if r["metric_name"] == "to_incentive_l1"][0]

        # Same INR amount / higher USD rate → lower USD value
        assert l1_90 < l1_80  # 90 INR/USD gives less USD than 80 INR/USD
        assert abs(l1_90 * 90 - l1_80 * 80) < 0.01  # INR amounts should be equal


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
            "months": {"2026-07": {
                "new_tos_per_month": 100, "to_retention_rate": 0.87,
                "tournaments_per_to_per_month": 10, "mau": 5000,
                "dau_mau_ratio": 0.15, "fill_rate": 0.7,
                "avg_teams_per_tournament": 16, "avg_players_per_team": 4,
                "usd_inr_rate": 90, "marketing_budgets": {},
                "ad_revenue": {}, "sponsorship": {}, "webshop_revenue": 0,
            }},
        }
        rows = compute_simulation(assumptions)
        tos = _get_values(rows, "active_tos")
        assert tos[0] == 100

    def test_zero_tournaments_no_division_error(self):
        assumptions = {
            "time_range": {"start_month": "2026-07", "end_month": "2026-07"},
            "seed_values": {"active_tos": 0},
            "months": {"2026-07": {
                "new_tos_per_month": 0, "to_retention_rate": 0,
                "tournaments_per_to_per_month": 0, "mau": 0,
                "dau_mau_ratio": 0, "fill_rate": 0,
                "avg_teams_per_tournament": 0, "avg_players_per_team": 0,
                "usd_inr_rate": 90, "marketing_budgets": {},
                "ad_revenue": {}, "sponsorship": {}, "webshop_revenue": 0,
            }},
        }
        rows = compute_simulation(assumptions)
        avg_p = [r for r in rows if r["metric_name"] == "avg_participants"]
        assert avg_p[0]["value"] == 0

    def test_missing_optional_fields_use_defaults(self):
        """Engine should handle missing optional fields gracefully."""
        assumptions = {
            "time_range": {"start_month": "2026-07", "end_month": "2026-07"},
            "seed_values": {},
            "months": {"2026-07": {
                "new_tos_per_month": 50,
                "usd_inr_rate": 90,
                "marketing_budgets": {},
                "ad_revenue": {},
                "sponsorship": {},
                "webshop_revenue": 0,
            }},
        }
        rows = compute_simulation(assumptions)
        tos = [r for r in rows if r["metric_name"] == "active_tos"]
        assert len(tos) == 1
        assert tos[0]["value"] == 50

    def test_time_range_filters_months(self):
        """Only months within time_range are computed."""
        assumptions = {
            "time_range": {"start_month": "2026-08", "end_month": "2026-09"},
            "seed_values": {"active_tos": 100},
            "months": {
                "2026-07": {"new_tos_per_month": 999, "usd_inr_rate": 90,
                            "marketing_budgets": {}, "ad_revenue": {},
                            "sponsorship": {}, "webshop_revenue": 0},
                "2026-08": {"new_tos_per_month": 50, "to_retention_rate": 0.9,
                            "usd_inr_rate": 90, "marketing_budgets": {},
                            "ad_revenue": {}, "sponsorship": {}, "webshop_revenue": 0},
                "2026-09": {"new_tos_per_month": 50, "to_retention_rate": 0.9,
                            "usd_inr_rate": 90, "marketing_budgets": {},
                            "ad_revenue": {}, "sponsorship": {}, "webshop_revenue": 0},
            },
        }
        rows = compute_simulation(assumptions)
        periods = {r["period_start"][:7] for r in rows}
        assert "2026-07" not in periods
        assert "2026-08" in periods
        assert "2026-09" in periods


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

    def test_all_values_are_numeric(self):
        for row in self.rows:
            assert isinstance(row["value"], (int, float)), f"Non-numeric value: {row}"

    def test_no_nan_or_inf(self):
        import math
        for row in self.rows:
            assert math.isfinite(row["value"]), f"Non-finite value: {row}"

    def test_expected_metric_names(self):
        names = {r["metric_name"] for r in self.rows}
        expected_names = {
            "active_tos", "total_tournaments", "mau", "dau",
            "inorganic_players", "demand_ua", "fill_rate",
            "total_player_slots", "avg_participants",
            "to_incentive_l1", "to_incentive_l2", "to_incentive_l3",
            "to_incentive_total", "sponsored_credits", "supply_ua",
            "ad_revenue", "sponsorship_revenue", "webshop_revenue",
            "total_revenue", "marketing_spend", "total_marketing_spend",
        }
        assert expected_names.issubset(names), f"Missing: {expected_names - names}"

    def test_six_months_of_data(self):
        periods = sorted({r["period_start"][:7] for r in self.rows})
        assert periods == ["2026-07", "2026-08", "2026-09", "2026-10", "2026-11", "2026-12"]

    def test_row_count(self):
        """Should have ~20 base metrics * 6 months + channel breakdowns."""
        assert len(self.rows) >= 120
