### Metrics API (/api/v1/metrics)

Manage metrics definitions and compute results. Nova supports six metric types:

| Type | What it does |
|------|-------------|
| `count` | Count events or unique users from event data |
| `aggregation` | SUM/AVG/MIN/MAX on a numeric event property |
| `ratio` | Divide two count queries (e.g. conversion rate) |
| `retention` | Cohort retention over a time window |
| `operational` | Query business data (spend, revenue, payouts) — not event-based |
| `formula` | Compose any metric types with arithmetic (e.g. CAC = spend / MAU) |

Common requirements:

- Bearer token and app context for all endpoints.
- SDK auth (`nova_sk_*` key) for `track-event` / `track-events`.

---

## Business Data

These endpoints handle **operational/business data** that isn't tied to user events — marketing spend, TO incentive payouts, sponsorship revenue, CPI costs, etc. This data goes into a dedicated ClickHouse table separate from the event stream.

#### POST /api/v1/metrics/business-data/

Ingest business data. Each row has a `metric_name` (what you're measuring), an optional `dimension` (breakdown key), a numeric `value`, and a `period_start` (the month/day this value covers).

Data is **upsert-safe**: re-uploading the same metric_name + dimension + period_start replaces the previous value instead of double-counting. This is backed by ClickHouse's ReplacingMergeTree engine.

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

#### GET /api/v1/metrics/business-data/schema/

Returns all distinct metric_name + dimension combinations that have been ingested. Use this to populate dropdown menus when building operational or formula metrics.

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

---

## Computing Metrics

#### POST /api/v1/metrics/compute/

Compute a metric ad-hoc. Supports all six metric types. The `config` shape varies by type.

##### count

Count events or unique users.

Request

```json
{
  "type": "count",
  "config": {
    "event_name": "session_start",
    "distinct": true,
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
  { "period": "2026-07-01", "value": 1200 },
  { "period": "2026-08-01", "value": 2500 }
]
```

##### aggregation

SUM/AVG/MIN/MAX on a numeric event property.

Request

```json
{
  "type": "aggregation",
  "config": {
    "event_name": "purchase",
    "property": "amount",
    "aggregation": "sum",
    "time_range": { "start": "2026-07-01 00:00:00", "end": "2026-09-01 00:00:00" },
    "granularity": "monthly",
    "group_by": [],
    "filters": {}
  }
}
```

##### ratio

Divide two count queries. Useful for conversion rates.

Request

```json
{
  "type": "ratio",
  "config": {
    "numerator": { "event_name": "purchase" },
    "denominator": { "event_name": "page_view" },
    "time_range": { "start": "2026-07-01 00:00:00", "end": "2026-09-01 00:00:00" },
    "granularity": "daily",
    "group_by": [],
    "filters": {}
  }
}
```

##### retention

Cohort retention: what % of users who did an initial event also did a return event within a time window.

Request

```json
{
  "type": "retention",
  "config": {
    "initial_event": { "event_name": "signup" },
    "return_event": { "event_name": "session_start" },
    "retention_window": "7d",
    "time_range": { "start": "2026-07-01 00:00:00", "end": "2026-09-01 00:00:00" },
    "granularity": "daily",
    "group_by": [],
    "filters": {}
  }
}
```

##### operational

Query the `business_metrics` table. Use this for financial/operational data that was ingested via `POST /business-data/`. Supports aggregation over time periods, grouping by dimension, and filtering to a specific dimension.

Request — total spend by month

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

Request — spend broken down by channel

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

Request — filter to a single channel

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

Config reference:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `metric_name` | string | yes | Must match a `metric_name` from ingested business data. |
| `aggregation` | string | yes | One of `sum`, `avg`, `min`, `max`. |
| `dimension_filter` | string | no | Filter to a specific dimension value. |
| `time_range` | object or string | yes | `{"start": "...", "end": "..."}` or relative like `"6m"`, `"30d"`. |
| `granularity` | string | yes | `hourly`, `daily`, `weekly`, `monthly`, or `none`. |
| `group_by` | array | no | Use `[{"key": "dimension", "source": ""}]` to group by dimension. |

##### formula

Compose multiple metrics with arithmetic. Each operand is a full metric definition (any type except formula). The expression supports `+`, `-`, `*`, `/`, parentheses, and numeric literals. Division automatically wraps the denominator with `nullIf(..., 0)` to prevent divide-by-zero errors.

The formula's `time_range` and `granularity` override whatever is set in the operand configs, ensuring all operands are computed over the same period.

Request — ROAS (revenue / spend)

```json
{
  "type": "formula",
  "config": {
    "time_range": { "start": "2026-07-01 00:00:00", "end": "2026-09-01 00:00:00" },
    "granularity": "monthly",
    "group_by": [],
    "operands": {
      "revenue": {
        "type": "operational",
        "config": { "metric_name": "total_revenue", "aggregation": "sum" }
      },
      "spend": {
        "type": "operational",
        "config": { "metric_name": "marketing_spend", "aggregation": "sum" }
      }
    },
    "expression": "revenue / spend"
  }
}
```

Response

```json
[
  { "period": "2026-07-01", "value": 0.15 },
  { "period": "2026-08-01", "value": 0.6538461538461539 }
]
```

Request — Net Margin (revenue - spend)

```json
{
  "type": "formula",
  "config": {
    "time_range": { "start": "2026-07-01 00:00:00", "end": "2026-09-01 00:00:00" },
    "granularity": "monthly",
    "group_by": [],
    "operands": {
      "revenue": {
        "type": "operational",
        "config": { "metric_name": "total_revenue", "aggregation": "sum" }
      },
      "spend": {
        "type": "operational",
        "config": { "metric_name": "marketing_spend", "aggregation": "sum" }
      }
    },
    "expression": "revenue - spend"
  }
}
```

Response

```json
[
  { "period": "2026-07-01", "value": -6800.0 },
  { "period": "2026-08-01", "value": -4500.0 }
]
```

You can mix event-based and operational operands. For example, CAC = Total Spend / MAU:

```json
{
  "type": "formula",
  "config": {
    "time_range": { "start": "2026-07-01 00:00:00", "end": "2026-09-01 00:00:00" },
    "granularity": "monthly",
    "group_by": [],
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
}
```

Config reference:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `operands` | object | yes | Map of name → `{type, config}`. Each operand is a full metric config. Type cannot be `formula` (no nesting). |
| `expression` | string | yes | Arithmetic expression using operand names. Allowed: `+`, `-`, `*`, `/`, `()`, numeric literals. |
| `time_range` | object or string | yes | Overrides all operand time ranges. |
| `granularity` | string | yes | Overrides all operand granularities. |
| `group_by` | array | no | Applied to all operands. Results joined on period + group keys. |

Common formula patterns:

| KPI | Expression | Operands |
|-----|-----------|----------|
| CAC | `spend / mau` | operational(marketing_spend) / count(distinct session_start) |
| ROAS | `revenue / spend` | operational(total_revenue) / operational(marketing_spend) |
| ARPU | `revenue / mau` | operational(total_revenue) / count(distinct session_start) |
| Net Margin | `revenue - spend` | operational(total_revenue) - operational(marketing_spend) |
| Cost per Tournament | `spend / tournaments` | operational(marketing_spend) / count(tournament.created) |
| Margin % | `(revenue - spend) / revenue` | Two operational operands with parenthesized expression |

---

## Metric CRUD

#### POST /api/v1/metrics/

Save a metric definition. The config is stored as-is and can later be passed to `/compute/`.

Request

```json
{
  "name": "ROAS",
  "description": "Return on Ad Spend = Total Revenue / Total Marketing Spend",
  "type": "formula",
  "config": {
    "time_range": "3m",
    "granularity": "monthly",
    "group_by": [],
    "operands": {
      "revenue": {
        "type": "operational",
        "config": { "metric_name": "total_revenue", "aggregation": "sum" }
      },
      "spend": {
        "type": "operational",
        "config": { "metric_name": "marketing_spend", "aggregation": "sum" }
      }
    },
    "expression": "revenue / spend"
  }
}
```

Response

```json
{
  "pid": "4f61feeb-06fc-46a0-9d3d-38fb61978fb8",
  "name": "ROAS",
  "description": "Return on Ad Spend = Total Revenue / Total Marketing Spend",
  "type": "formula",
  "config": { ... }
}
```

#### GET /api/v1/metrics/

List all saved metrics.

Response

```json
[
  {
    "pid": "4f61feeb-06fc-46a0-9d3d-38fb61978fb8",
    "name": "ROAS",
    "description": "Return on Ad Spend = Total Revenue / Total Marketing Spend",
    "type": "formula",
    "config": { ... }
  },
  {
    "pid": "389d1427-06d6-48f5-a2ff-6bfd280f2e52",
    "name": "Monthly Marketing Spend",
    "description": "Total marketing spend aggregated by month",
    "type": "operational",
    "config": { ... }
  }
]
```

#### GET /api/v1/metrics/{metric_id}/

Get a metric by id.

Response: metric object.

#### PUT /api/v1/metrics/{metric_id}/

Update a metric.

Request: same shape as POST.

Response: updated metric object.

---

## Event Schema Discovery

#### GET /api/v1/metrics/events-schema/

List known event schemas (auto-discovered from tracked events).

Query params: `search` (optional string)

Response

```json
[
  {
    "pid": "<uuid>",
    "event_name": "purchase",
    "event_schema": { "properties": { "amount": { "type": "int" }, "currency": { "type": "str" } } }
  }
]
```

#### GET /api/v1/metrics/user-profile-keys/

List known user profile keys (auto-discovered from profile updates).

Query params: `search` (optional string)

Response

```json
[
  {
    "pid": "<uuid>",
    "key": "country",
    "type": "str",
    "description": ""
  }
]
```

---

## Common Config Fields

These fields are shared across all metric types:

| Field | Type | Description |
|-------|------|-------------|
| `time_range` | `{"start": "YYYY-MM-DD HH:MM:SS", "end": "..."}` or string like `"7d"`, `"30d"`, `"6m"` | Time range to query. Relative strings calculated from current UTC time. |
| `granularity` | `hourly`, `daily`, `weekly`, `monthly`, `none` | Time bucketing for results. |
| `group_by` | array of `{"key": "<name>", "source": "<source>"}` | Group results by a dimension. Sources: `event_properties`, `user_profile`, `user_experience`, or empty string for operational dimension. |
| `filters` | object | Key-value filters. Each filter has `value`, `source`, and `op` (`=`, `!=`, `>`, `<`, `>=`, `<=`). |
