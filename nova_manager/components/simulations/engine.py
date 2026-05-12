"""GTM KPI Simulation Engine.

Pure computation module — no database or ClickHouse imports.
Takes an assumptions dict, computes all derived metrics month-by-month,
returns a list of business_metrics rows ready for ingestion.
"""

from datetime import datetime


def compute_simulation(assumptions: dict) -> list[dict]:
    """Compute all derived metrics from input assumptions.

    Args:
        assumptions: Dict with keys: time_range, seed_values, months.
            See the assumptions JSON schema in the plan for structure.

    Returns:
        List of dicts with keys: metric_name, dimension, value, period_start, currency.
        Ready to pass to EventsController.ingest_business_metrics().
    """
    time_range = assumptions["time_range"]
    seed = assumptions.get("seed_values", {})
    months_data = assumptions["months"]

    # Sort months chronologically
    sorted_months = sorted(months_data.keys())

    # Validate time_range matches months
    start = time_range["start_month"]
    end = time_range["end_month"]
    sorted_months = [m for m in sorted_months if start <= m <= end]

    if not sorted_months:
        return []

    rows = []
    prev_active_tos = seed.get("active_tos", 0)

    for month in sorted_months:
        m = months_data[month]
        period_start = f"{month}-01T00:00:00Z"
        usd_inr = m.get("usd_inr_rate", 90)

        # ── Supply cascade ──────────────────────────────────
        new_tos = m.get("new_tos_per_month", 0)
        retention = m.get("to_retention_rate", 0.87)

        if month == sorted_months[0]:
            # First month: seed + new TOs (no retention from prior)
            active_tos = prev_active_tos * retention + new_tos if prev_active_tos > 0 else new_tos
        else:
            active_tos = prev_active_tos * retention + new_tos

        tournaments_per_to = m.get("tournaments_per_to_per_month", 10)
        grimm_bot = m.get("grimm_bot_tournaments", 0)
        total_tournaments = active_tos * tournaments_per_to + grimm_bot

        # ── Demand ──────────────────────────────────────────
        mau = m.get("mau", 0)
        dau_mau_ratio = m.get("dau_mau_ratio", 0.15)
        dau = mau * dau_mau_ratio

        pct_inorganic = m.get("pct_inorganic_players", 0)
        inorganic_players = mau * pct_inorganic

        player_cpi = m.get("player_cpi", 0)
        demand_ua = inorganic_players * player_cpi

        # ── Engagement ──────────────────────────────────────
        avg_teams = m.get("avg_teams_per_tournament", 16)
        avg_players = m.get("avg_players_per_team", 4)
        fill_rate = m.get("fill_rate", 0.7)

        total_player_slots = total_tournaments * avg_teams * avg_players * fill_rate
        avg_participants = total_player_slots / total_tournaments if total_tournaments > 0 else 0

        # ── TO Incentives (INR → USD) ───────────────────────
        milestone_reward = m.get("milestone_reward_per_to_inr", 3500)
        leaderboard_pool = m.get("leaderboard_pool_inr", 240000)
        grand_prize = m.get("grand_prize_amortized_inr", 300000)

        to_incentive_l1_inr = active_tos * milestone_reward
        to_incentive_l2_inr = leaderboard_pool
        to_incentive_l3_inr = grand_prize

        to_incentive_l1 = to_incentive_l1_inr / usd_inr
        to_incentive_l2 = to_incentive_l2_inr / usd_inr
        to_incentive_l3 = to_incentive_l3_inr / usd_inr
        to_incentive_total = to_incentive_l1 + to_incentive_l2 + to_incentive_l3

        # ── Sponsored Credits (INR → USD) ───────────────────
        initial_credit_per_to = m.get("initial_credit_per_to_inr", 2000)
        initial_credit_new_users = m.get("initial_credit_new_users_inr", 0)
        r1_rate = m.get("r1_achievement_rate", 0)
        r2_rate = m.get("r2_achievement_rate", 0)
        refill_amount_inr = 1500  # fixed per Excel spec

        initial_credit_inr = active_tos * initial_credit_per_to + initial_credit_new_users
        refill_inr = (r1_rate + r2_rate) * refill_amount_inr * active_tos
        total_sponsored_credits_inr = initial_credit_inr + refill_inr
        sponsored_credits = total_sponsored_credits_inr / usd_inr

        # ── Supply UA ───────────────────────────────────────
        supply_ua = to_incentive_total + sponsored_credits

        # ── Ad Revenue ──────────────────────────────────────
        ad_params = m.get("ad_revenue", {})
        static_imp = ad_params.get("static_impressions_per_dau", 0)
        inter_imp = ad_params.get("interstitial_impressions_per_dau", 0)
        video_imp = ad_params.get("video_impressions_per_dau", 0)
        ecpm_static = ad_params.get("ecpm_static", 0)
        ecpm_inter = ad_params.get("ecpm_interstitial", 0)
        ecpm_video = ad_params.get("ecpm_video", 0)
        ad_fill_rate = ad_params.get("ad_fill_rate", 0)

        daily_ad_rev = dau * (
            static_imp * ecpm_static +
            inter_imp * ecpm_inter +
            video_imp * ecpm_video
        ) / 1000 * ad_fill_rate
        ad_revenue = round(daily_ad_rev * 30)  # 30-day months, rounded per Excel

        # ── Sponsorship & Webshop ───────────────────────────
        sponsor = m.get("sponsorship", {})
        active_deals = sponsor.get("active_deals", 0)
        avg_deal_value = sponsor.get("avg_deal_value", 0)
        sponsorship_revenue = active_deals * avg_deal_value

        webshop_revenue = m.get("webshop_revenue", 0)

        # ── Totals ──────────────────────────────────────────
        total_revenue = ad_revenue + sponsorship_revenue + webshop_revenue

        # Marketing spend by channel
        budgets = m.get("marketing_budgets", {})
        other_paid_total = sum(budgets.values())
        total_marketing_spend = supply_ua + demand_ua + other_paid_total

        # ── Emit rows ───────────────────────────────────────
        def emit(name, value, dimension="", currency="USD"):
            rows.append({
                "metric_name": name,
                "dimension": dimension,
                "value": value,
                "period_start": period_start,
                "currency": currency,
            })

        # Supply
        emit("active_tos", active_tos)
        emit("total_tournaments", total_tournaments)
        emit("to_incentive_l1", to_incentive_l1, "milestones")
        emit("to_incentive_l2", to_incentive_l2, "leaderboard")
        emit("to_incentive_l3", to_incentive_l3, "grand_prize")
        emit("to_incentive_total", to_incentive_total)
        emit("sponsored_credits", sponsored_credits)
        emit("supply_ua", supply_ua)

        # Demand
        emit("mau", mau)
        emit("dau", dau)
        emit("inorganic_players", inorganic_players)
        emit("demand_ua", demand_ua)

        # Engagement
        emit("fill_rate", fill_rate)
        emit("total_player_slots", total_player_slots)
        emit("avg_participants", avg_participants)

        # Revenue
        emit("ad_revenue", ad_revenue)
        emit("sponsorship_revenue", sponsorship_revenue)
        emit("webshop_revenue", webshop_revenue)
        emit("total_revenue", total_revenue)

        # Marketing by channel
        for channel, amount in budgets.items():
            if amount:
                emit("marketing_spend", amount, channel)
        emit("total_marketing_spend", total_marketing_spend)

        # Carry forward
        prev_active_tos = active_tos

    return rows
