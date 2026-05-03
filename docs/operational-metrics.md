### Operational Metrics

The `operational` metric type queries the `business_metrics` ClickHouse table — data ingested via [`POST /business-data/`](business-data.md). Use this for financial and operational KPIs that aren't derived from user events: marketing spend, revenue, TO payouts, CPI costs, etc.

Computed via `POST /api/v1/metrics/compute/` with `"type": "operational"`.

---

#### Total spend by month

```json
{
  "type": "operational",
  "config": {
    "metric_name": "marketing_spend",
    "aggregation": "sum",
    "time_range": { "start": "2026-07-01 00:00:00", "end": "2026-09-01 00:00:00" },
    "granularity": "monthly",
    "group_by": [],
    "filters": {}
  }
}
```

Response

```json
[
  { "period": "2026-07-01", "value": 8000.0 },
  { "period": "2026-08-01", "value": 13000.0 }
]
```

---

#### Spend broken down by channel

Use `group_by` with `dimension` to get per-channel breakdowns.

```json
{
  "type": "operational",
  "config": {
    "metric_name": "marketing_spend",
    "aggregation": "sum",
    "time_range": { "start": "2026-07-01 00:00:00", "end": "2026-09-01 00:00:00" },
    "granularity": "monthly",
    "group_by": [{ "key": "dimension", "source": "" }],
    "filters": {}
  }
}
```

Response

```json
[
  { "period": "2026-07-01", "dimension": "facebook", "value": 3000.0 },
  { "period": "2026-07-01", "dimension": "google_ads", "value": 5000.0 },
  { "period": "2026-08-01", "dimension": "facebook", "value": 5000.0 },
  { "period": "2026-08-01", "dimension": "google_ads", "value": 8000.0 }
]
```

---

#### Filter to a single channel

Use `dimension_filter` to restrict results to one dimension value.

```json
{
  "type": "operational",
  "config": {
    "metric_name": "marketing_spend",
    "dimension_filter": "google_ads",
    "aggregation": "sum",
    "time_range": { "start": "2026-07-01 00:00:00", "end": "2026-09-01 00:00:00" },
    "granularity": "monthly",
    "group_by": [],
    "filters": {}
  }
}
```

Response

```json
[
  { "period": "2026-07-01", "value": 5000.0 },
  { "period": "2026-08-01", "value": 8000.0 }
]
```

---

#### Config reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `metric_name` | string | yes | Must match a `metric_name` from ingested business data. |
| `aggregation` | string | yes | One of `sum`, `avg`, `min`, `max`. |
| `dimension_filter` | string | no | Filter to a specific dimension value. |
| `time_range` | object or string | yes | `{"start": "...", "end": "..."}` or relative like `"6m"`, `"30d"`. |
| `granularity` | string | yes | `hourly`, `daily`, `weekly`, `monthly`, or `none`. |
| `group_by` | array | no | Use `[{"key": "dimension", "source": ""}]` to group by dimension. |
