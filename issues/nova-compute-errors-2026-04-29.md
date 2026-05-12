# Nova `/metrics/compute/` — Frontend-Verified Error Report

**Date:** 2026-04-29
**Endpoint:** `POST https://api.nova.xgaming.club/api/v1/metrics/compute/`
**Auth:** Bearer from `POST /api/v1/auth/login` (admin@krafton.com)
**Range:** `2026-03-18 12:17:18` → `2026-04-17 12:17:18`

Replace `$TOKEN` in any curl with a valid bearer.

---

## Cross-verification against frontend

The frontend's metric form (`OverviewTab.tsx` + `metricPayload.ts`) only emits these shapes:

```ts
const FILTER_OPS = ['=', '!=', '>', '<', '>=', '<=', 'LIKE', 'NOT LIKE', 'IN', 'NOT IN'];
const AGGREGATION_OPS = ['sum', 'avg', 'min', 'max'];
type MetricType = 'count' | 'aggregation' | 'ratio' | 'retention';
```

So the frontend never sends `op:eq` (it sends `=`) and never sends `aggregation:count` or `aggregation:distinct_count` (those aren't in the form). My initial report flagged those — they're real Nova-side issues but **don't hit the frontend path**.

After re-testing with frontend-exact payloads, the only bug that actually breaks a real frontend flow is **retention**.

---

## Summary

| Type | Frontend variant | Result |
|------|------------------|--------|
| count | basic / distinct / weekly / monthly / hourly | ✅ |
| count | group_by | ✅ |
| count | filter `op:'='` (frontend default) | ✅ |
| count | filter `op:'!='` / `'LIKE'` / `'>'` / etc. | ✅ |
| aggregation | sum / avg / min / max on numeric property | ✅ |
| ratio | basic / distinct / weekly | ✅ |
| **retention** | **any window, any event pair** | **❌** |

**One real frontend bug.** Retention is fully blocked.

---

## ❌ Bug — Retention is completely broken

Every retention call 500s regardless of payload. The generated SQL has an identifier-resolution mistake in the `filtered_returns` CTE.

### curl (frontend-exact shape: D1 retention — login → login next day)

```bash
curl -X POST 'https://api.nova.xgaming.club/api/v1/metrics/compute/' \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{
    "type": "retention",
    "config": {
      "initial_event": {"event_name": "auth.login_success"},
      "return_event":  {"event_name": "auth.login_success"},
      "retention_window": "1d",
      "time_range": {"start": "2026-03-18 12:17:18", "end": "2026-04-17 12:17:18"},
      "granularity": "daily",
      "group_by": [],
      "filters": {}
    }
  }'
```

### Response — HTTP 500

```
DB::Exception: Identifier 'fr.user_id' cannot be resolved from subquery with name fr.
In scope WITH initial_cohort AS (SELECT toStartOfDay(e.client_ts) AS cohort_period, e.user_id AS user_id, MIN(e.client_ts) AS first_ts FROM ... raw_events AS e WHERE (e.event_name = 'auth.login_success') ...),
     return_events AS (SELECT r.user_id AS user_id, r.client_ts AS ret_ts FROM ... raw_events AS r WHERE ...),
     filtered_returns AS (SELECT i.cohort_period, r.user_id, r.ret_ts FROM initial_cohort AS i INNER JOIN return_events AS r ON r.user_id = i.user_id WHERE (r.ret_ts > i.first_ts) AND (r.ret_ts < (i.first_ts + toIntervalDay(1))))
SELECT i.cohort_period AS period,
       uniqExact(i.user_id) AS cohort_users,
       uniqExactIf(i.user_id, fr.ret_ts IS NOT NULL) AS retained_users,
       uniqExactIf(i.user_id, fr.ret_ts IS NOT NULL) / nullIf(uniqExact(i.user_id), 0) AS value
FROM initial_cohort AS i
LEFT JOIN filtered_returns AS fr ON (fr.user_id = i.user_id) AND (fr.cohort_period = i.cohort_period)
GROUP BY i.cohort_period
ORDER BY i.cohort_period ASC.
Maybe you meant: ['r.user_id']. (UNKNOWN_IDENTIFIER)
```

### Root cause

`filtered_returns` selects `r.user_id` and `r.ret_ts` **without aliasing**. ClickHouse keeps those identifiers as `r.user_id`/`r.ret_ts` even when the CTE is aliased `fr`. The outer `LEFT JOIN ... ON fr.user_id = i.user_id` then can't resolve `fr.user_id`.

### Fix (Nova-side)

Alias inside the CTE:

```sql
filtered_returns AS (
  SELECT i.cohort_period,
         r.user_id  AS user_id,
         r.ret_ts   AS ret_ts
  FROM initial_cohort AS i
  INNER JOIN return_events AS r ON r.user_id = i.user_id
  WHERE r.ret_ts > i.first_ts
    AND r.ret_ts < i.first_ts + toIntervalDay(N)
)
```

### Reproduced with

| Initial event | Return event | Window | Granularity | Result |
|---|---|---|---|---|
| auth.login_success | auth.login_success | 1d | daily | ❌ |
| auth.login_success | tournament.viewed | 7d | daily | ❌ |
| organizer.signup_started | tournament.created | 14d | weekly | ❌ |

---

## Server-side issues that don't currently affect frontend

These would matter if the frontend ever exposed the relevant options. Logged for completeness but **not blocking** today.

### Status table

| Capability | Nova schema-level | Nova execution | Frontend exposed? |
|---|---|---|---|
| `aggregation:count` | accepted | ❌ Float64 cast on property | no |
| `aggregation:distinct_count` | accepted | ❌ `UNKNOWN_FUNCTION DISTINCT_COUNT` | no |
| filter `op:eq/ne/gt/...` (legacy short codes) | accepted | ❌ injected as raw SQL keyword | no (frontend uses `=`, `!=`) |
| filter `op:IS NULL` / `IS NOT NULL` | accepted | ❌ value still appended to SQL → syntax error | no |
| filter `op:BETWEEN` | accepted | ❌ value placement broken (`expected token after BETWEEN`) | no |
| filter `op:IN` with list value | accepted | ❌ value escaped wrong | no |
| filter `op:ILIKE` / `NOT ILIKE` | accepted | ✅ works | no |
| filter `op:REGEXP` | accepted | ✅ works | no |
| `source:'user_profile'` for filter / group_by | accepted | ⚠ no SQL error but result key is empty (no actual lookup) | no |
| custom retention window (`3d`, `60d`, `12h`, `2w`) | accepted | ❌ same retention bug as standard windows | no (only `7d/14d/30d/24h/1w`) |
| `KeyError`-style 500 on missing required fields | rejected (sort of) | ❌ 500 with bare key name | no (form requires fields client-side) |

### Reproducer — IS NULL / IS NOT NULL (filter value appended even for unary ops)

```bash
curl -X POST 'https://api.nova.xgaming.club/api/v1/metrics/compute/' \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"type":"count","config":{"event_name":"screen.viewed","distinct":false,"time_range":{"start":"2026-03-18 12:17:18","end":"2026-04-17 12:17:18"},"granularity":"daily","group_by":[],"filters":{"raw_path":{"source":"event_properties","op":"IS NULL","value":""}}}}'
```
→ 500 `SYNTAX_ERROR ... ('GROUP BY ...') Expected one of: ..., IS NULL, IS NOT NULL, ...`. The empty `value` is concatenated as `IS NULL ''`, breaking the WHERE clause.

### Reproducer — BETWEEN

```bash
curl -X POST 'https://api.nova.xgaming.club/api/v1/metrics/compute/' \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"type":"aggregation","config":{"event_name":"tournament.creation_step_completed","property":"step_number","aggregation":"sum","time_range":{"start":"2026-03-18 12:17:18","end":"2026-04-17 12:17:18"},"granularity":"daily","group_by":[],"filters":{"step_number":{"source":"event_properties","op":"BETWEEN","value":"1 AND 5"}}}}'
```
→ 500 `SYNTAX_ERROR ... at 'GROUP'`. The `BETWEEN` op needs special argument handling (two endpoints), which Nova's filter renderer doesn't do.

### Reproducer — IN with list

```bash
curl -X POST 'https://api.nova.xgaming.club/api/v1/metrics/compute/' \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"type":"count","config":{"event_name":"screen.viewed","distinct":false,"time_range":{"start":"2026-03-18 12:17:18","end":"2026-04-17 12:17:18"},"granularity":"daily","group_by":[],"filters":{"screen_name":{"source":"event_properties","op":"IN","value":"('Home','Profile')"}}}}'
```
→ 500 `SYNTAX_ERROR ... ('Home', 'Profile')`. The `value` string is single-quoted whole, so the inner quotes break parsing. `IN` needs a list-value codec, not a string-passthrough.

### Reproducer — `source:'user_profile'`

```bash
curl -X POST 'https://api.nova.xgaming.club/api/v1/metrics/compute/' \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"type":"count","config":{"event_name":"auth.login_success","distinct":false,"time_range":{"start":"2026-03-18 12:17:18","end":"2026-04-17 12:17:18"},"granularity":"daily","group_by":[{"key":"is_new_user","source":"user_profile"}],"filters":{}}}'
```
→ 200 — but the response has `"is_new_user":""` for every row, suggesting the `user_profile` source either isn't actually joined or returns empty for unknown keys silently. No SQL error, just no real grouping. **Soft fail — looks like it works but doesn't.**

### Reproducer — Custom retention windows

Tested `3d`, `60d`, `12h`, `2w`. All four fail with the same `Identifier 'fr.user_id' cannot be resolved` error documented under the main retention bug. Nothing window-specific — just confirms the retention SQL is broken regardless of input.

---

## ✅ What works (frontend-verified happy paths)

### count

```bash
curl -X POST 'https://api.nova.xgaming.club/api/v1/metrics/compute/' \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"type":"count","config":{"event_name":"auth.login_success","distinct":false,"time_range":{"start":"2026-03-18 12:17:18","end":"2026-04-17 12:17:18"},"granularity":"daily","group_by":[],"filters":{}}}'
```

Confirmed working: `distinct=true`, `granularity=hourly|weekly|monthly`, `group_by`, all `FILTER_OPS` (`=`, `!=`, `LIKE`, `>`, etc.).

### aggregation (sum/avg/min/max on numeric property)

```bash
curl -X POST 'https://api.nova.xgaming.club/api/v1/metrics/compute/' \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"type":"aggregation","config":{"event_name":"tournament.creation_step_completed","property":"step_number","aggregation":"sum","time_range":{"start":"2026-03-18 12:17:18","end":"2026-04-17 12:17:18"},"granularity":"daily","group_by":[],"filters":{}}}'
```

Confirmed for `sum | avg | min | max` on int properties (`step_number`, `total_steps`).

### ratio

```bash
curl -X POST 'https://api.nova.xgaming.club/api/v1/metrics/compute/' \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"type":"ratio","config":{"numerator":{"event_name":"tournament.created","distinct":false},"denominator":{"event_name":"tournament.creation_started","distinct":false},"time_range":{"start":"2026-03-18 12:17:18","end":"2026-04-17 12:17:18"},"granularity":"daily","group_by":[],"filters":{}}}'
```

Real product ratios verified: `created/creation_started`, `otp_success/requested`, `tournament.created/organizer.signup_started`.

---

## Action items

**Nova team — must fix:**
- Retention CTE alias bug (single-CTE change, blocks the entire retention metric type).

**Nova team — nice to have (no frontend impact today):**
- Filter operator translation
- `count` aggregation Float64 cast
- `distinct_count` SQL mapping
- 400 vs 500 + better error envelope

**Frontend — no changes required.** Current payloads match the API schema correctly; bugs are entirely server-side.
