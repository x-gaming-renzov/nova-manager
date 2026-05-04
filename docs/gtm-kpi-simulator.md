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

## Seed script

A seed script is included that loads data from the Battlin GTM KPI Simulator Excel and validates all 9 KPIs end-to-end:

```bash
# Dry run — see what would be ingested
python3 -m scripts.seed_gtm_kpis --dry-run --sheet v2

# Run against a live server
python3 -m scripts.seed_gtm_kpis --base-url http://localhost:8000 --sheet v2

# Other scenarios from the Excel
python3 -m scripts.seed_gtm_kpis --sheet neutral
python3 -m scripts.seed_gtm_kpis --sheet positive
python3 -m scripts.seed_gtm_kpis --sheet akshay
```

The script creates a fresh account, ingests 152 business data rows from the selected Excel scenario, saves all 9 formula metrics, computes each one, and compares the results against the Excel's expected values.

---

## What's next

The current system handles metrics that can be expressed as arithmetic on values within the same time period. The Excel simulator also contains metrics that depend on previous months — for example, Active TOs next month equals this month's TOs times retention rate plus new TOs. Supporting these cascading, time-dependent calculations is the next step. See the [architecture review](../HANDOFF.md) for the planned simulation engine.
