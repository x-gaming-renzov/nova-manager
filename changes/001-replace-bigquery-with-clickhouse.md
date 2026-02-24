# Replace BigQuery with ClickHouse

## Context

nova-manager uses Google BigQuery for event analytics (event tracking, metrics computation, user profile tracking). This needs to change because:
1. **Client wants Azure** — BigQuery is GCP-only
2. **Local dev is impossible** — BigQuery requires GCP credentials, no clean local option
3. **Vendor lock-in** — BigQuery SQL dialect + Python SDK tightly couples us to GCP

**Decision**: Replace with **ClickHouse** because it runs in Docker (local dev), runs on Azure (ClickHouse Cloud), is columnar/analytics-optimized (same tier as BigQuery), and has a SQL dialect close to standard SQL.

---

## Scope Summary

**4 files change significantly, 4 files need minor edits, 3 infrastructure files update, 1 file deleted, 2 new files created.**

| Category | Files |
|---|---|
| Replace entirely | `service/bigquery.py` → new `service/clickhouse_service.py` |
| Heavy changes | `components/metrics/events_controller.py`, `components/metrics/query_builder.py` |
| Moderate changes | `components/metrics/artefacts.py`, `api/auth/router.py` |
| Minor changes | `api/metrics/router.py`, `core/config.py`, `components/user_experience/crud_async.py` (comment only) |
| Infrastructure | `docker-compose.yml`, `pyproject.toml`, `.env` |
| Delete | `service/bigquery.py`, `scripts/bootstrap_bigquery.py` |
| New files | `service/clickhouse_service.py`, `scripts/bootstrap_clickhouse.py` |
| **NO changes needed** | `api/users/router.py`, `components/user_experience/event_listeners.py`, `queues/controller.py`, `main.py`, `Dockerfile`, `generate_test_events.py` |

---

## Key Design Decision: Unified Tables

**Current BigQuery approach** creates dynamic per-event tables:
```
org_X_app_Y.events_button_click       (one table per event type)
org_X_app_Y.event_button_click_props  (one props table per event type)
org_X_app_Y.raw_events                (all events combined)
org_X_app_Y.user_profile_props
org_X_app_Y.user_experience
```

**New ClickHouse approach** uses unified tables per database:
```
org_X_app_Y.raw_events           (ALL events, filtered by event_name column)
org_X_app_Y.event_props          (ALL event properties, filtered by event_name)
org_X_app_Y.user_profile_props   (same as before)
org_X_app_Y.user_experience      (same as before)
```

**Why**: ClickHouse MergeTree engine with `ORDER BY (event_name, user_id, client_ts)` gives the same query performance as separate tables because it skips irrelevant data granules by the ordering key. Per-event tables was a BigQuery-specific optimization that adds unnecessary complexity in ClickHouse.

**Impact**: `create_event_table()` and `create_event_props_table(event_name)` methods disappear. QueryBuilder changes FROM clauses from `FROM events_{name}` to `FROM raw_events WHERE event_name = '{name}'`.

---

## ClickHouse Table Schemas

```sql
-- Database per org/app (replaces BigQuery "dataset")
CREATE DATABASE IF NOT EXISTS org_{org}_app_{app};

-- Replaces: raw_events + all per-event events_* tables
CREATE TABLE raw_events (
    event_id    String,
    user_id     String,
    event_name  String,
    event_data  String,          -- JSON stored as string
    client_ts   DateTime64(3),
    server_ts   DateTime64(3)
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(client_ts)
ORDER BY (event_name, user_id, client_ts);

-- Replaces: all per-event event_*_props tables
CREATE TABLE event_props (
    event_id    String,
    user_id     String,
    event_name  String,
    key         String,
    value       String,
    client_ts   DateTime64(3),
    server_ts   DateTime64(3)
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(client_ts)
ORDER BY (event_name, user_id, key, client_ts);

-- Same structure, now in ClickHouse
CREATE TABLE user_profile_props (
    user_id   String,
    key       String,
    value     String,
    server_ts DateTime64(3)
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(server_ts)
ORDER BY (user_id, key, server_ts);

-- Same structure, now in ClickHouse
CREATE TABLE user_experience (
    user_id               String,
    experience_id         String,
    personalisation_id    String,
    personalisation_name  String,
    experience_variant_id String,
    features              String,
    evaluation_reason     String,
    assigned_at           DateTime64(3)
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(assigned_at)
ORDER BY (user_id, experience_id, assigned_at);
```

---

## Step-by-Step Changes

### Step 1: `nova_manager/core/config.py`

**Remove**:
```python
GCP_PROJECT_ID = getenv("GCP_PROJECT_ID") or ""
GOOGLE_APPLICATION_CREDENTIALS = getenv("GOOGLE_APPLICATION_CREDENTIALS") or ""
BIGQUERY_LOCATION = getenv("BIGQUERY_LOCATION") or "US"
```

**Add**:
```python
CLICKHOUSE_HOST = getenv("CLICKHOUSE_HOST") or "localhost"
CLICKHOUSE_PORT = int(getenv("CLICKHOUSE_PORT") or "8123")
CLICKHOUSE_USER = getenv("CLICKHOUSE_USER") or "default"
CLICKHOUSE_PASSWORD = getenv("CLICKHOUSE_PASSWORD") or ""
```

---

### Step 2: New file `nova_manager/service/clickhouse_service.py`

Drop-in replacement for `BigQueryService`. Key methods:
- `insert_rows(table_name, rows)` — uses `clickhouse-connect` client's `insert()` method
- `run_query(query)` — returns `list[dict]` (same as BigQueryService, but without pandas)
- `execute(statement)` — for DDL (CREATE TABLE, CREATE DATABASE)
- `create_database_if_not_exists(database_name)` — replaces `create_dataset_if_not_exists`
- `create_table_if_not_exists(ddl_sql)` — takes raw SQL string instead of schema dict (ClickHouse DDL includes ENGINE, PARTITION, ORDER BY which don't fit a simple schema dict)

Then **delete** `nova_manager/service/bigquery.py`.

---

### Step 3: `nova_manager/components/metrics/artefacts.py`

Simplify the naming class. Remove per-event-name methods, rename dataset → database:

| Before | After |
|---|---|
| `_dataset_name()` | `_database_name()` |
| `_event_table_name(event_name)` | **Remove** |
| `_event_props_table_name(event_name)` | `_event_props_table_name()` (no arg) |
| `_raw_events_table_name()` | Keep — returns `{db}.raw_events` |
| `_user_experience_table_name()` | Keep |
| `_user_profile_props_table_name()` | Keep |

Also rename `self.dataset_name` → `self.database_name` in `__init__`.

---

### Step 4: `nova_manager/components/metrics/events_controller.py` (heaviest change)

**Imports**: Replace `BigQueryService` → `ClickHouseService`, remove `GCP_PROJECT_ID` import.

**Methods that change**:

| Method | Change |
|---|---|
| `create_dataset()` | Rename to `create_database()`, call `ClickHouseService().create_database_if_not_exists()` |
| `create_raw_events_table()` | Build ClickHouse DDL string, call `create_table_if_not_exists(ddl)` |
| `create_event_table(event_name)` | **Delete** — unified tables, no per-event tables |
| `create_event_props_table(event_name)` | Replace with `create_event_props_table()` (no arg) — creates unified `event_props` table |
| `create_user_profile_table()` | ClickHouse DDL |
| `create_user_experience_table()` | ClickHouse DDL |
| `push_to_bigquery(...)` | Rename to `push_to_clickhouse()`. Signature simplifies: `(raw_events_rows, event_props_rows)` — flat lists, no per-event dicts |
| `track_events(...)` | Remove dynamic table creation for new events. Flatten event_props_rows. Call `push_to_clickhouse()`. PostgreSQL EventsSchema logic stays identical. |
| `track_user_experience(...)` | Replace `BigQueryService().insert_rows()` → `ClickHouseService().insert_rows()`. Remove redundant `create_user_experience_table()` call. |
| `track_user_profile(...)` | Same swap. Remove redundant `create_user_profile_table()` call. |

**Key detail in `track_events()`**: Currently builds 3 data structures:
- `raw_events_rows` (list) — stays the same
- `event_table_rows` (dict keyed by event_name) — **removed entirely** (raw_events already has this data)
- `event_props_table_rows` (dict keyed by event_name) — **flattened to a single list**

---

### Step 5: `nova_manager/components/metrics/query_builder.py` (SQL translation)

**A) Function translations**:

| BigQuery | ClickHouse |
|---|---|
| `TIMESTAMP_TRUNC({ts}, HOUR)` | `toStartOfHour({ts})` |
| `DATE_TRUNC({ts}, DAY)` | `toStartOfDay({ts})` |
| `DATE_TRUNC({ts}, WEEK)` | `toMonday({ts})` |
| `DATE_TRUNC({ts}, MONTH)` | `toStartOfMonth({ts})` |
| `TIMESTAMP('1970-01-01 00:00:00')` | `toDateTime('1970-01-01 00:00:00')` |
| `SAFE_DIVIDE(a, b)` | `a / nullIf(b, 0)` |
| `CAST(val AS FLOAT64)` | `toFloat64(val)` |
| `IFNULL(a, b)` | `ifNull(a, b)` |
| `COUNT(DISTINCT IF(cond, col, NULL))` | `uniqIf(col, cond)` |
| `COUNT(DISTINCT col)` | `uniq(col)` |
| `TIMESTAMP_ADD(ts, INTERVAL n UNIT)` | `ts + INTERVAL n UNIT` (same) |

**B) Table reference changes** (unified tables):

All query methods (`_build_count_query`, `_build_aggregation_query`, `_build_ratio_query`, `_build_retention_query`):
- `FROM events_{event_name}` → `FROM raw_events WHERE event_name = '{name}'`
- Property joins: `LEFT JOIN event_{name}_props` → `LEFT JOIN event_props` (add `event_name` to join condition)
- Retention CTEs: same pattern for both initial and return event subqueries

**C) Update maps**:

```python
GRANULARITY_TRUNC_MAP = {
    "hourly": "toStartOfHour({ts})",
    "daily": "toStartOfDay({ts})",
    "weekly": "toMonday({ts})",
    "monthly": "toStartOfMonth({ts})",
    "none": "toDateTime('1970-01-01 00:00:00')",
}
```

`UNIT_SQL_MAP` stays identical (ClickHouse uses same INTERVAL syntax).

---

### Step 6: `nova_manager/api/metrics/router.py` (minor)

- Change import: `BigQueryService` → `ClickHouseService`
- Line 106-107: `BigQueryService().run_query(query)` → `ClickHouseService().run_query(query)`

---

### Step 7: `nova_manager/api/auth/router.py` (minor)

- Line 276: `events_controller.create_dataset()` → `events_controller.create_database()`
- Add line: `events_controller.create_event_props_table()` (new unified table, provisioned during app creation)
- Lines 287-290: Update error messages from "BigQuery" to "analytics tables"

---

### Step 8: `docker-compose.yml`

Add ClickHouse + Redis services, remove GCP env vars:

```yaml
services:
  postgres:
    image: postgres:15-alpine
    ports:
      - "5432:5432"
    environment:
      - POSTGRES_USER=nova
      - POSTGRES_PASSWORD=nova
      - POSTGRES_DB=nova
    networks:
      - nova-network

  clickhouse:
    image: clickhouse/clickhouse-server:24.8-alpine
    ports:
      - "8123:8123"
      - "9000:9000"
    volumes:
      - clickhouse_data:/var/lib/clickhouse
    networks:
      - nova-network

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    networks:
      - nova-network

  nova-manager:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://nova:nova@postgres:5432/nova
      - REDIS_URL=redis://redis:6379/0
      - CLICKHOUSE_HOST=clickhouse
      - CLICKHOUSE_PORT=8123
    depends_on:
      - postgres
      - clickhouse
      - redis
    # ...rest stays same

  worker:
    # same env var changes as nova-manager
```

---

### Step 9: `pyproject.toml`

**Remove**: `google-cloud-bigquery`, `pandas`, `db-dtypes`
**Add**: `clickhouse-connect (>=0.8.0,<1.0.0)`

Then run: `poetry lock && poetry install`

---

### Step 10: New file `scripts/bootstrap_clickhouse.py`

Replaces `scripts/bootstrap_bigquery.py`. Much simpler — iterates all apps from PostgreSQL, calls `EventsController.create_database()` + the 4 `create_*_table()` methods. No per-event-type table iteration needed.

Delete `scripts/bootstrap_bigquery.py`.

---

### Step 11: Verify `generate_test_events.py`

Should work unchanged — it only calls `EventsController.track_events()` which keeps the same public signature `(user_id, events)`. Just run it and verify.

---

## Call Chain Verification (No Changes Needed)

These paths work through `EventsController` with unchanged method signatures:

```
POST /users/create-user/
  → api/users/router.py
  → QueueController.add_task(EventsController.track_user_profile, ...)
  → NO CHANGES NEEDED (track_user_profile keeps same signature)

SQLAlchemy after_insert on UserExperience
  → event_listeners.py
  → QueueController.add_task(EventsController.track_user_experience, ...)
  → NO CHANGES NEEDED (track_user_experience keeps same signature)

UserExperienceAsyncCRUD.bulk_create_user_experience_personalisations
  → crud_async.py
  → QueueController.add_task(EventsController.track_user_experience, ...)
  → NO CHANGES NEEDED (only update "BigQuery" → "ClickHouse" in comment)
```

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| DateTime format mismatch | Insert failures | `clickhouse-connect` accepts ISO 8601 strings for `DateTime64`. Test with actual inserts. |
| `toMonday()` ≠ `DATE_TRUNC(WEEK)` | Weekly metrics off by a day | Document that weeks start Monday (ISO 8601). Use `toStartOfWeek(ts, 1)` if Sunday needed. |
| `uniq()` is approximate | Retention/count metrics slightly off | Use `uniqExact()` if exact counts needed. For analytics dashboards, `uniq()` is standard practice. |
| ClickHouse String columns not nullable by default | Insert failures if NULLs passed | Current code already converts everything to `str()`. No NULLs expected. |
| No transactions in ClickHouse | Partial inserts on error | Same as BigQuery streaming inserts — already non-transactional. Log errors, move on. |

---

## Verification Plan

1. `docker compose up` — verify all services start (Postgres, ClickHouse, Redis)
2. Register user + create app via `POST /auth/register` → `POST /auth/apps` — verify ClickHouse database + 4 tables are created
3. Create a user via `POST /users/create-user/` with `user_profile` — verify insert into `user_profile_props` in ClickHouse
4. Track events via `POST /metrics/track-event/` — verify inserts into `raw_events` + `event_props`
5. Create a metric and compute via `POST /metrics/compute/` — verify ClickHouse query returns results
6. Trigger experience assignment via `POST /user-experience/` — verify insert into `user_experience` in ClickHouse
7. Run `poetry run python scripts/bootstrap_clickhouse.py` — verify idempotent
8. Run `poetry run python generate_test_events.py` — verify bulk event generation works

---

## Execution Order (Critical Path)

```
Step 1 (config) ─→ Step 2 (clickhouse_service.py) ─→ Step 3 (artefacts.py)
                                                          │
                                              ┌───────────┴───────────┐
                                              v                       v
                                    Step 4 (events_controller)   Step 5 (query_builder)
                                              │                       │
                                              v                       v
                                    Step 7 (auth/router)        Step 6 (metrics/router)

Steps 8, 9 (docker-compose, pyproject.toml) — independent, do anytime
Step 10 (bootstrap script) — after Steps 2-4
Step 11 (verify test script) — after everything
```
