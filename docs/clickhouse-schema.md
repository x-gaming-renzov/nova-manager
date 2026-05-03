# ClickHouse Database Schema

This document describes how Nova Manager stores events, user profiles, user experiences, and metrics data in ClickHouse.

## Database Naming Convention

Each organisation/app pair gets its own ClickHouse database:

```
org_{organisation_id}_app_{app_id}
```

Special characters in IDs are sanitized to underscores (`[^a-zA-Z0-9_]` → `_`).

**Example:** `org_abc123_app_xyz789`

Databases are created on-demand when an app first tracks events, or in bulk via `scripts/bootstrap_clickhouse.py`.

---

## Tables

Four tables use the **MergeTree** engine and one uses **ReplacingMergeTree**, all with monthly partitioning for efficient time-range pruning.

### 1. `raw_events` — Event log

Stores one row per tracked event. All event types go into this single unified table (filtered by `event_name`).

```sql
CREATE TABLE raw_events (
    event_id   String,
    user_id    String,
    event_name String,
    event_data String,          -- JSON payload stored as a string
    client_ts  DateTime64(3),   -- client-supplied timestamp (ms precision)
    server_ts  DateTime64(3)    -- server receipt timestamp
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(client_ts)
ORDER BY (event_name, user_id, client_ts)
```

| Column | Purpose |
|---|---|
| `event_id` | UUID, unique per event |
| `user_id` | External user identifier |
| `event_name` | Discriminator — all queries filter on this first |
| `event_data` | Full event payload as JSON string |
| `client_ts` | When the event happened (client side) |
| `server_ts` | When the server received the event |

**ORDER BY** `(event_name, user_id, client_ts)` — optimises the most common access pattern: "all events of type X for user Y in time range Z".

---

### 2. `event_props` — Flattened event properties

Each key/value pair from an event's payload is stored as a separate row. This enables efficient filtering and grouping on individual properties without parsing JSON.

```sql
CREATE TABLE event_props (
    event_id   String,
    user_id    String,
    event_name String,
    key        String,
    value      String,
    client_ts  DateTime64(3),
    server_ts  DateTime64(3)
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(client_ts)
ORDER BY (event_name, user_id, key, client_ts)
```

| Column | Purpose |
|---|---|
| `event_id` | Links back to `raw_events.event_id` |
| `key` | Property name (e.g. `"plan"`, `"amount"`) |
| `value` | Property value cast to string |

**Joined to `raw_events`** via:
```sql
LEFT JOIN event_props AS p
  ON e.event_id = p.event_id
 AND p.event_name = '<name>'
 AND p.key = '<key>'
```

---

### 3. `user_profile_props` — User profile attributes

User profile data stored as key-value rows. Only changed attributes are appended (delta tracking). The latest value is resolved at query time using `ROW_NUMBER()`.

```sql
CREATE TABLE user_profile_props (
    user_id   String,
    key       String,
    value     String,
    server_ts DateTime64(3)
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(server_ts)
ORDER BY (user_id, key, server_ts)
```

| Column | Purpose |
|---|---|
| `user_id` | External user identifier |
| `key` | Profile attribute name (e.g. `"country"`, `"plan"`) |
| `value` | Attribute value as string |
| `server_ts` | When the change was recorded |

**Latest-value query pattern:**
```sql
SELECT user_id, key, value
FROM (
    SELECT *, ROW_NUMBER() OVER (
        PARTITION BY user_id, key ORDER BY server_ts DESC
    ) AS rn
    FROM user_profile_props
    WHERE key = '<key>'
) WHERE rn = 1
```

---

### 4. `user_experience` — Personalisation assignments

Tracks which experience/personalisation variant a user was assigned to. Like profiles, this is append-only and the latest assignment is resolved with `ROW_NUMBER()`.

```sql
CREATE TABLE user_experience (
    user_id              String,
    experience_id        String,
    personalisation_id   String,
    personalisation_name String,
    experience_variant_id String,
    features             String,          -- JSON string
    evaluation_reason    String,
    assigned_at          DateTime64(3)
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(assigned_at)
ORDER BY (user_id, experience_id, assigned_at)
```

| Column | Purpose |
|---|---|
| `experience_id` | The experience being evaluated |
| `personalisation_id` | Specific personalisation within the experience |
| `personalisation_name` | Human-readable name |
| `experience_variant_id` | Variant the user was placed in |
| `features` | Feature flags / config as JSON string |
| `evaluation_reason` | Why this assignment was made |
| `assigned_at` | Assignment timestamp |

---

### 5. `business_metrics` — Operational/business data

Stores financial and operational data that is not tied to user events: marketing spend, TO incentive payouts, sponsorship revenue, CPI costs, etc. This data is ingested via `POST /api/v1/metrics/business-data/` and queried by the `operational` metric type.

Uses **ReplacingMergeTree** instead of MergeTree. This means re-ingesting the same metric_name + dimension + period_start replaces the previous value rather than creating a duplicate. Queries must use `FINAL` to read deduplicated data.

```sql
CREATE TABLE business_metrics (
    metric_name  String,
    dimension    String,
    value        Float64,
    currency     String DEFAULT '',
    period_start DateTime64(3),
    created_at   DateTime64(3)
) ENGINE = ReplacingMergeTree(created_at)
PARTITION BY toYYYYMM(period_start)
ORDER BY (metric_name, dimension, period_start)
```

| Column | Purpose |
|---|---|
| `metric_name` | What is being measured (e.g. `marketing_spend`, `total_revenue`, `to_incentive_payout`) |
| `dimension` | Breakdown key (e.g. `google_ads`, `facebook`, `tier_1`). Empty string if dimensionless. |
| `value` | Numeric value (Float64). Must be finite. |
| `currency` | Optional currency code (e.g. `USD`). |
| `period_start` | Start of the period this value covers. |
| `created_at` | Insertion timestamp. Used by ReplacingMergeTree to keep the latest row on dedup. |

**ORDER BY** `(metric_name, dimension, period_start)` — this is also the dedup key. Re-inserting the same combination replaces the old row.

**Query pattern (with FINAL for dedup):**
```sql
SELECT toStartOfMonth(period_start) AS period, SUM(value) AS value
FROM business_metrics FINAL
WHERE metric_name = 'marketing_spend'
  AND period_start >= '2026-07-01' AND period_start < '2026-10-01'
GROUP BY period
ORDER BY period
```

---

## Data Flow

### Event ingestion

```
SDK → track_events() → raw_events  (one row per event)
                     → event_props (one row per key in event_data)
```

1. Each event gets a UUID `event_id`.
2. The full JSON payload is stored in `raw_events.event_data`.
3. Each top-level key from the payload is flattened into `event_props` for queryability.
4. Event schemas (property names + types) are tracked separately in PostgreSQL for UI/validation.

### User profile updates

```
SDK → track_user_profile() → user_profile_props (one row per changed key)
```

Only keys that actually changed compared to the previous profile are written. Profile key metadata is also synced to PostgreSQL.

### Experience assignment

```
evaluate_experience() → user_experience (one row per assignment)
```

Recorded whenever a user is assigned (or re-assigned) to an experience variant.

### Business data ingestion

```
Dashboard → POST /business-data/ → business_metrics (one row per data point)
```

Operational data (spend, revenue, payouts) is inserted directly without going through the async job queue. ReplacingMergeTree handles upserts.

---

## Query Patterns & Metrics

The `QueryBuilder` generates ClickHouse SQL for six metric types:

| Metric | Description | Key ClickHouse features used |
|---|---|---|
| **Count** | Count events or unique users | `COUNT(*)`, `uniqExact(user_id)` |
| **Aggregation** | SUM/AVG/MIN/MAX on a property | `toFloat64()` cast on `event_props.value` |
| **Ratio** | Numerator count / denominator count | `nullIf(den, 0)` for safe division, CTEs |
| **Retention** | Cohort retention over a time window | `uniqExactIf()`, `INTERVAL` arithmetic |
| **Operational** | Query `business_metrics` table (spend, revenue) | `FINAL` for ReplacingMergeTree dedup |
| **Formula** | Compose N metrics with arithmetic | CTEs per operand, `nullIf` for safe division |

### Time bucketing

Queries support these granularities via ClickHouse time-truncation functions:

| Granularity | Function |
|---|---|
| `hourly` | `toStartOfHour(ts)` |
| `daily` | `toStartOfDay(ts)` |
| `weekly` | `toMonday(ts)` |
| `monthly` | `toStartOfMonth(ts)` |

### Filter & group-by sources

Queries can filter and group by data from three sources, each with its own join strategy:

| Source | Table joined | Join key |
|---|---|---|
| `event_properties` | `event_props` | `event_id` + `key` |
| `user_profile` | `user_profile_props` | `user_id` + `key` (latest via `ROW_NUMBER`) |
| `user_experience` | `user_experience` | `user_id` (latest via `ROW_NUMBER`) |

---

## Connection Configuration

Set via environment variables (defaults in parentheses):

| Variable | Default |
|---|---|
| `CLICKHOUSE_HOST` | `localhost` |
| `CLICKHOUSE_PORT` | `8123` |
| `CLICKHOUSE_USER` | `default` |
| `CLICKHOUSE_PASSWORD` | (empty) |

Client library: [`clickhouse-connect`](https://clickhouse.com/docs/en/integrations/python) with lazy-initialised connections.

