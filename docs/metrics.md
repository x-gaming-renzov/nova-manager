### Metrics API (/api/v1/metrics)

Manage metrics definitions and compute results. Nova supports six metric types:

| Type | What it does | Docs |
|------|-------------|------|
| `count` | Count events or unique users from event data | below |
| `aggregation` | SUM/AVG/MIN/MAX on a numeric event property | below |
| `ratio` | Divide two count queries (e.g. conversion rate) | below |
| `retention` | Cohort retention over a time window | below |
| `operational` | Query business data (spend, revenue, payouts) | [operational-metrics.md](operational-metrics.md) |
| `formula` | Compose any metric types with arithmetic | [formula-metrics.md](formula-metrics.md) |

Business data ingestion (the data that `operational` metrics query) is documented in [business-data.md](business-data.md).

Common requirements:

- Bearer token and app context for all endpoints.
- SDK auth (`nova_sk_*` key) for `track-event` / `track-events`.

---

## Computing Metrics

#### POST /api/v1/metrics/compute/

Compute a metric ad-hoc. The `config` shape varies by type.

##### count

Count events or unique users.

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

##### operational / formula

See [operational-metrics.md](operational-metrics.md) and [formula-metrics.md](formula-metrics.md).

---

## Metric CRUD

#### POST /api/v1/metrics/

Save a metric definition. The config is stored as-is and can later be passed to `/compute/`. Works for all six metric types.

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

Response: array of metric objects.

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

These fields are shared across metric types:

| Field | Type | Description |
|-------|------|-------------|
| `time_range` | `{"start": "YYYY-MM-DD HH:MM:SS", "end": "..."}` or string like `"7d"`, `"30d"`, `"6m"` | Time range to query. Relative strings calculated from current UTC time. |
| `granularity` | `hourly`, `daily`, `weekly`, `monthly`, `none` | Time bucketing for results. |
| `group_by` | array of `{"key": "<name>", "source": "<source>"}` | Group results by a dimension. Sources: `event_properties`, `user_profile`, `user_experience`, or empty string for operational dimension. |
| `filters` | object | Key-value filters. Each filter has `value`, `source`, and `op` (`=`, `!=`, `>`, `<`, `>=`, `<=`). |
