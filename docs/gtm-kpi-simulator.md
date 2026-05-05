# GTM KPI Simulator

Track, measure, and simulate your go-to-market performance from a single dashboard. The GTM KPI Simulator lets you ingest real business data — marketing spend, revenue, user counts, tournament activity — then define formula-based KPIs that update automatically as new data comes in.

---

## What it does

You have a spreadsheet with your GTM plan. Monthly targets for spend, MAU, tournaments, revenue. Derived metrics like CAC, ROAS, and margin that update when you tweak inputs. The simulator brings that into Nova so your KPIs are live, queryable, and tied to actual data — not a static file passed around on Slack.

**Ingest business data** — Upload marketing spend by channel, revenue by source, tournament counts, user numbers, and any other operational metric. Data is upsert-safe: re-uploading a corrected value replaces the old one without double-counting.

**Define formula KPIs** — Combine any metrics with arithmetic. CAC is spend divided by MAU. ROAS is revenue divided by spend. Margin is revenue minus spend divided by revenue. You write the expression, Nova builds the query.

**Query on demand** — Every formula computes live against the latest ingested data. Change August's spend, re-query CAC, see the new number immediately. No manual recalculation.

---

## Supported KPIs

These are the KPIs validated against the Battlin GTM KPI Simulator spreadsheet. All 9 match the Excel to floating-point precision across 6 months of data.

| KPI | What it measures | Formula |
|-----|-----------------|---------|
| **CAC** | Customer Acquisition Cost | Total Marketing Spend / MAU |
| **ROAS** | Return on Ad Spend | Total Revenue / Total Marketing Spend |
| **ARPU** | Average Revenue Per User | Total Revenue / MAU |
| **Net Margin** | Profit (or loss) | Total Revenue - Total Marketing Spend |
| **Margin %** | Margin as a ratio | (Revenue - Spend) / Revenue |
| **Supply CAC** | Cost per Tournament Organizer | Total Supply UA / Active TOs |
| **Demand CAC** | Cost per acquired player | Total Demand UA / Inorganic Players |
| **Cost per Tournament** | Marketing efficiency | Total Marketing Spend / Total Tournaments |
| **Revenue per Tournament** | Monetization efficiency | Total Revenue / Total Tournaments |

These are starting points. You can define any formula that combines addition, subtraction, multiplication, and division across your ingested metrics.

---

## How it works

### 1. Ingest your data

Upload operational data to Nova. Each data point has a name, an optional dimension (breakdown key), a value, and a period.

```
POST /api/v1/metrics/business-data/
```

```json
{
  "data": [
    { "metric_name": "marketing_spend", "dimension": "google_ads",  "value": 5000,  "period_start": "2026-07-01T00:00:00Z" },
    { "metric_name": "marketing_spend", "dimension": "facebook",    "value": 3000,  "period_start": "2026-07-01T00:00:00Z" },
    { "metric_name": "total_revenue",   "dimension": "",            "value": 12418, "period_start": "2026-10-01T00:00:00Z" },
    { "metric_name": "mau",             "dimension": "",            "value": 120000,"period_start": "2026-10-01T00:00:00Z" }
  ]
}
```

You can upload as many metrics as you need. Common ones for the Battlin GTM flow:

| Category | Metrics |
|----------|---------|
| Supply | `active_tos`, `total_tournaments`, `supply_ua`, `sponsored_credits` |
| Demand | `mau`, `dau`, `inorganic_players`, `demand_ua` |
| Marketing | `marketing_spend` (with channel dimensions), `total_marketing_spend` |
| Revenue | `ad_revenue`, `sponsorship_revenue`, `webshop_revenue`, `total_revenue` |
| Incentives | `to_incentive_l1`, `to_incentive_l2`, `to_incentive_l3` |

### 2. Define a KPI

Save a formula metric that references your ingested data.

```
POST /api/v1/metrics/
```

```json
{
  "name": "CAC",
  "description": "Customer Acquisition Cost = Total Marketing Spend / MAU",
  "type": "formula",
  "config": {
    "time_range": { "start": "2026-07-01 00:00:00", "end": "2027-01-01 00:00:00" },
    "granularity": "monthly",
    "group_by": [],
    "operands": {
      "spend": {
        "type": "operational",
        "config": { "metric_name": "total_marketing_spend", "aggregation": "sum" }
      },
      "mau": {
        "type": "operational",
        "config": { "metric_name": "mau", "aggregation": "sum" }
      }
    },
    "expression": "spend / mau"
  }
}
```

The `expression` field is plain arithmetic using the operand names you defined. Division is automatically safe — if the denominator is zero, the result is NULL instead of an error.

### 3. Compute it

Query the metric on demand. The result updates live whenever underlying data changes.

```
POST /api/v1/metrics/compute/
```

```json
{
  "type": "formula",
  "config": {
    "time_range": { "start": "2026-07-01 00:00:00", "end": "2027-01-01 00:00:00" },
    "granularity": "monthly",
    "group_by": [],
    "operands": {
      "spend": {
        "type": "operational",
        "config": { "metric_name": "total_marketing_spend", "aggregation": "sum" }
      },
      "mau": {
        "type": "operational",
        "config": { "metric_name": "mau", "aggregation": "sum" }
      }
    },
    "expression": "spend / mau"
  }
}
```

Response:

```json
[
  { "period": "2026-07-01", "value": 2.19 },
  { "period": "2026-08-01", "value": 1.79 },
  { "period": "2026-09-01", "value": 2.05 },
  { "period": "2026-10-01", "value": 0.95 },
  { "period": "2026-11-01", "value": 0.66 },
  { "period": "2026-12-01", "value": 0.40 }
]
```

### 4. Discover what's available

See all metric names and dimensions that have been ingested, so you know what you can query.

```
GET /api/v1/metrics/business-data/schema/
```

```json
[
  { "metric_name": "marketing_spend", "dimension": "google_ads" },
  { "metric_name": "marketing_spend", "dimension": "facebook" },
  { "metric_name": "mau",             "dimension": "" },
  { "metric_name": "total_revenue",   "dimension": "" }
]
```

---

## Mixing data sources

Formula operands don't have to be the same type. You can combine business data with live event analytics:

```json
{
  "operands": {
    "spend": {
      "type": "operational",
      "config": { "metric_name": "marketing_spend", "aggregation": "sum" }
    },
    "mau": {
      "type": "count",
      "config": { "event_name": "session_start", "distinct": true }
    }
  },
  "expression": "spend / mau"
}
```

Here `spend` comes from uploaded business data, while `mau` is computed live from the event stream. This is useful when some numbers come from finance (spend) and others from product analytics (active users).

---

## Expressions

Write formulas the way you'd write them on paper:

| Expression | What it computes |
|-----------|-----------------|
| `spend / mau` | Simple division |
| `revenue - spend` | Subtraction |
| `(revenue - spend) / revenue` | Parenthesized expression |
| `spend * 100 / revenue` | Numeric literals work |
| `(revenue - spend) / mau` | Three operands, mixed arithmetic |

Division by zero returns NULL (not an error). Parentheses are supported and validated for balance. Only arithmetic operators and your operand names are allowed — no SQL, no injection risk.

---

## Simulations

Instead of uploading pre-computed values from Excel, you can define a simulation with input assumptions and let Nova compute all derived metrics automatically — including cascading calculations that depend on previous months (e.g., `Active TOs[Aug] = Active TOs[Jul] * retention + new TOs`).

### Create a simulation

```
POST /api/v1/simulations/
```

```json
{
  "name": "GTM V2 Scenario",
  "description": "Aggressive growth — 200 new TOs/month",
  "scenario_id": "scenario_v2",
  "assumptions": {
    "time_range": { "start_month": "2026-07", "end_month": "2026-12" },
    "seed_values": { "active_tos": 0 },
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
        "fill_rate": 0.7,
        "milestone_reward_per_to_inr": 3500,
        "leaderboard_pool_inr": 240000,
        "grand_prize_amortized_inr": 300000,
        "initial_credit_per_to_inr": 2000,
        "r1_achievement_rate": 0,
        "r2_achievement_rate": 0,
        "usd_inr_rate": 90,
        "marketing_budgets": { "bgmi_giveaways": 5000 },
        "ad_revenue": {
          "static_impressions_per_dau": 10,
          "ecpm_static": 0.15,
          "ad_fill_rate": 0.5
        },
        "sponsorship": { "active_deals": 0, "avg_deal_value": 0 },
        "webshop_revenue": 0
      },
      "2026-08": { "..." : "..." }
    }
  }
}
```

Each month has its own set of assumptions — retention rates, spend budgets, eCPMs, etc. The engine computes everything else.

### Run it

```
POST /api/v1/simulations/{simulation_id}/run/
```

This computes all derived metrics month-by-month and writes ~140 data points to ClickHouse under the simulation's `scenario_id`. The computation is synchronous and sub-second.

Response:

```json
{
  "run": {
    "pid": "4ba1ba6c-...",
    "status": "completed",
    "metrics_written": 140,
    "created_at": "2026-05-05T07:00:00Z",
    "completed_at": "2026-05-05T07:00:00Z"
  },
  "metrics_written": 140
}
```

Re-running is safe — ClickHouse deduplicates on the same metric+period+scenario.

### What the engine computes

Given your input assumptions, the engine runs these cascading calculations for each month:

| Step | Metric | Formula |
|------|--------|---------|
| 1 | Active TOs | previous month * retention + new TOs |
| 2 | Total Tournaments | Active TOs * tournaments/TO + GRIMM bot |
| 3 | DAU | MAU * DAU/MAU ratio |
| 4 | Inorganic Players | MAU * % inorganic |
| 5 | Player Slots | Tournaments * teams * players * fill rate |
| 6 | TO Incentives (L1-L3) | Based on active TOs, milestone rewards, pools |
| 7 | Sponsored Credits | Initial + refills based on achievement rates |
| 8 | Supply UA | Incentives + sponsored credits |
| 9 | Demand UA | Inorganic players * CPI |
| 10 | Ad Revenue | DAU * impressions * eCPM * fill rate |
| 11 | Sponsorship Revenue | Active deals * deal value |
| 12 | Total Revenue | Ad + sponsorship + webshop |
| 13 | Total Marketing Spend | Supply UA + demand UA + channel budgets |

After the engine writes these values, the existing formula metrics (CAC, ROAS, ARPU, etc.) query them with the `scenario_id` filter — no additional setup needed.

### Query results

Use the same `/metrics/compute/` endpoint with `scenario_id` in operand configs:

```json
{
  "type": "formula",
  "config": {
    "time_range": { "start": "2026-07-01 00:00:00", "end": "2027-01-01 00:00:00" },
    "granularity": "monthly",
    "group_by": [],
    "operands": {
      "spend": { "type": "operational", "config": { "metric_name": "total_marketing_spend", "aggregation": "sum", "scenario_id": "scenario_v2" } },
      "mau": { "type": "operational", "config": { "metric_name": "mau", "aggregation": "sum", "scenario_id": "scenario_v2" } }
    },
    "expression": "spend / mau"
  }
}
```

### Other simulation endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET /simulations/ | List all simulations | Supports `status` filter |
| GET /simulations/{id}/ | Get simulation with assumptions | |
| PUT /simulations/{id}/ | Update name, description, or assumptions | scenario_id is immutable |
| DELETE /simulations/{id}/ | Delete simulation and run history | |
| GET /simulations/{id}/runs/ | List run history | Ordered by most recent |

### Assumptions reference

Each month in the `assumptions.months` object supports these fields:

| Field | Type | Description |
|-------|------|-------------|
| `new_tos_per_month` | int | New Tournament Organizers added |
| `to_retention_rate` | float | Month-over-month TO retention (e.g., 0.87) |
| `tournaments_per_to_per_month` | int | Tournaments each TO runs |
| `grimm_bot_tournaments` | int | Automated tournaments (e.g., 50 from Oct) |
| `mau` | int | Monthly Active Users target |
| `dau_mau_ratio` | float | DAU as fraction of MAU |
| `pct_inorganic_players` | float | Fraction of MAU that are paid-acquired |
| `player_cpi` | float | Cost per install (USD) |
| `fill_rate` | float | Tournament fill rate (0-1) |
| `milestone_reward_per_to_inr` | float | L1 incentive per TO (INR) |
| `leaderboard_pool_inr` | float | L2 monthly pool (INR) |
| `grand_prize_amortized_inr` | float | L3 amortized monthly (INR) |
| `initial_credit_per_to_inr` | float | Sponsored credit per TO (INR) |
| `initial_credit_new_users_inr` | float | Sponsored credit for new users (INR) |
| `r1_achievement_rate` | float | Refill rate for 10+ tournaments |
| `r2_achievement_rate` | float | Refill rate for 20+ tournaments |
| `usd_inr_rate` | float | Exchange rate |
| `marketing_budgets` | object | Per-channel spend (e.g., `{"social_channel": 5000}`) |
| `ad_revenue` | object | Impressions/DAU and eCPMs per ad type |
| `sponsorship` | object | `{"active_deals": N, "avg_deal_value": N}` |
| `webshop_revenue` | float | Webshop revenue (USD) |

---

## Seed script

A seed script is included that loads data from the Battlin GTM KPI Simulator Excel and validates all 9 KPIs end-to-end:

```bash
# Single scenario
python3 -m scripts.seed_gtm_kpis --base-url http://localhost:8000 --sheet v2

# All 4 scenarios under one account
python3 -m scripts.seed_gtm_kpis --base-url http://localhost:8000 --all-scenarios

# Via simulation API (creates simulation, runs engine, validates output)
python3 -m scripts.seed_gtm_kpis --base-url http://localhost:8000 --sheet v2 --via-simulation

# Dry run
python3 -m scripts.seed_gtm_kpis --dry-run --sheet v2
```
