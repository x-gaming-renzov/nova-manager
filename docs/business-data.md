### Business Data API (/api/v1/metrics/business-data)

Ingest and discover **operational/business data** — marketing spend, TO incentive payouts, sponsorship revenue, CPI costs, and any other financial data that isn't tied to user events.

This data goes into a dedicated ClickHouse table (`business_metrics`) separate from the event stream. It is queried by the `operational` metric type and can be combined with event-based metrics via the `formula` metric type.

---

#### POST /api/v1/metrics/business-data/

Ingest business data. Each row has a `metric_name` (what you're measuring), an optional `dimension` (breakdown key), a numeric `value`, and a `period_start` (the month/day this value covers).

Data is **upsert-safe**: re-uploading the same metric_name + dimension + period_start replaces the previous value instead of double-counting. This is backed by ClickHouse's ReplacingMergeTree engine.

Auth: Bearer token with app context.

Request

```json
{
  "data": [
    {
      "metric_name": "marketing_spend",
      "dimension": "google_ads",
      "value": 5000.00,
      "period_start": "2026-07-01T00:00:00Z",
      "currency": "USD"
    },
    {
      "metric_name": "marketing_spend",
      "dimension": "facebook",
      "value": 3000.00,
      "period_start": "2026-07-01T00:00:00Z",
      "currency": "USD"
    },
    {
      "metric_name": "total_revenue",
      "dimension": "ad_revenue",
      "value": 1200.00,
      "period_start": "2026-07-01T00:00:00Z",
      "currency": "USD"
    },
    {
      "metric_name": "to_incentive_payout",
      "dimension": "tier_1",
      "value": 2000.00,
      "period_start": "2026-07-01T00:00:00Z",
      "currency": "USD"
    }
  ]
}
```

Response

```json
{
  "success": true,
  "count": 4
}
```

Field reference:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `metric_name` | string | yes | Identifier for the metric (e.g. `marketing_spend`, `total_revenue`). Alphanumeric, underscore, hyphen, dot only. Max 256 chars. |
| `dimension` | string | no | Breakdown key (e.g. `google_ads`, `tier_1`). Defaults to empty string. |
| `value` | float | yes | Numeric value. Must be finite (no NaN/Infinity). |
| `period_start` | datetime | yes | Start of the period this value covers. ISO 8601 format. |
| `currency` | string | no | Currency code (e.g. `USD`). Max 10 chars. |

Common metric names used in the GTM KPI flow:

| Category | metric_name | Example dimensions |
|----------|-------------|-------------------|
| Supply | `active_tos`, `total_tournaments`, `supply_ua` | (none) |
| Supply costs | `to_incentive_l1`, `to_incentive_l2`, `to_incentive_l3`, `sponsored_credits` | `milestones`, `leaderboard`, `grand_prize` |
| Demand | `mau`, `dau`, `inorganic_players`, `demand_ua` | (none) |
| Marketing | `marketing_spend`, `total_marketing_spend` | `to_empowerment`, `prize_pools`, `social_channel`, `college_activation`, `kol_influencer`, `seo_aso`, `bgmi_giveaways`, `pr_media`, `marquee_tourney` |
| Revenue | `ad_revenue`, `sponsorship_revenue`, `webshop_revenue`, `total_revenue` | (none) |
| Engagement | `fill_rate`, `total_player_slots`, `avg_participants` | (none) |

---

#### GET /api/v1/metrics/business-data/schema/

Returns all distinct metric_name + dimension combinations that have been ingested. Use this to populate dropdown menus when building operational or formula metrics.

Auth: Bearer token with app context.

Response

```json
[
  { "metric_name": "marketing_spend", "dimension": "facebook" },
  { "metric_name": "marketing_spend", "dimension": "google_ads" },
  { "metric_name": "to_incentive_payout", "dimension": "tier_1" },
  { "metric_name": "total_revenue", "dimension": "ad_revenue" },
  { "metric_name": "total_revenue", "dimension": "sponsorship" }
]
```
