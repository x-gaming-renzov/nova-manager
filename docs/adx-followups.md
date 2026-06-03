# ADX integration: follow-ups

Snapshot date: **2026-06-03**. Verify file:line references against current code before acting — the codebase moves.

This doc is written so an agent with zero prior knowledge of this codebase can pick up the work. Memories in `~/.claude/projects/.../memory/` cover commit style and DB topology; everything else needed should be in this doc plus the linked code.

---

## 0. TL;DR

Nova-manager is XGaming's analytics + experimentation backend. Until recently it used ClickHouse for analytics storage. The active branch `feature/adx-integration` migrates it to Azure Data Explorer (ADX, also known as Kusto). The cutover is **per-app** — an `apps.analytics_backend` column ("clickhouse" or "adx") routes each app independently, so apps can be moved one at a time. The Batlin app in prod is already set to `analytics_backend='adx'`.

**Current state:** Core paths work end-to-end. 12 of 42 overwatch E2E tests pass reliably; the remaining 30 are gated on a single Nova robustness bug (P0 below) that causes a cascade under any transient ADX issue. For "shared testing surface" prod usage, what's landed is usable. For real customer load, fix P0 first.

---

## 1. Where things live

### Repos
- **`nova-manager`** (this repo) — the analytics backend. Branch `feature/adx-integration` is where ADX work happens. Remote: `github.com/x-gaming-renzov/nova-manager`.
- **`Krafton-ESports-python-backend`** (Overwatch) — the admin/dashboard service that consumes Nova's API. Path: `~/Documents/mystuff/x/repos/Krafton-ESports-python-backend`. Branch: `jeera/analytics`. Remote: `github.com/Krafton-Gaminn/Krafton-ESports-python-backend`.
- **`Krafton-ESports-wallet-service-xg`** — wallet service. Path: `~/Documents/mystuff/x/repos/Krafton-ESports-wallet-service-xg`. Only relevant to overwatch's wallet-pipeline tests.

### Deployments
- **Nova prod** — GCP Cloud Run, project `xgaminn`, region `us-central1`. Deploy script: `deploy_to_gcp.sh`. Postgres is GCP Cloud SQL (`xgaminn:us-central1:nova-db`). Secrets in GCP Secret Manager (`DATABASE_URL`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, etc.).
- **Nova local dev** — uvicorn on `localhost:8000` typically. `.env` at repo root configures DB + Azure. The user's local Postgres has multiple working DBs; `nova_manager3` is the active one. See memory `prod-db-topology` for full list.

### ADX cluster
- **URI**: `https://kresadxdev.centralindia.kusto.windows.net`
- **Cluster name**: `kresadxdev`
- **Tenant**: `1a27bdbf-e6cc-4e33-85d2-e1c81bad930a`
- **Resource group**: `KR-ESports-RG-Dev`
- **Subscription**: "Battlin Project"
- **SKU**: dev/basic (see P2 — won't handle "millions of users" load)
- **Service principal** (used by Cloud Run): client_id `ee5ab084-4d8f-46cf-85b7-c12546ee2720`, secret in GCP Secret Manager as `AZURE_CLIENT_SECRET`.

### ADX databases
- **`org_test_db_check`** — shared test DB. Tables empty between sessions (tests use unique scenario_ids). Has the 5 lowercase tables: `raw_events`, `event_props`, `user_profile_props`, `user_experience`, `business_metrics`.
- **`org_fa7b153b_..._app_6fa6d19b_...`** — Batlin (main prod app). 49,470 rows (as of 2026-06-03; CH has 63,199 — there's drift, see §5).
- **`org_c1c5efad_..._app_03c1d3de_...`** — Overwatch's own app DB.
- **`kr-es-analytics-dev`** — legacy infra-created, do not use (has PascalCase tables with tenant columns).
- **`kr-es-analytics-staging`** — staging.

Database naming convention: `org_{org_uuid_with_underscores}_app_{app_uuid_with_underscores}`. UUID dashes become underscores. See `sanitize()` in `scripts/migrate_ch_to_adx.py`.

### ClickHouse (legacy, being phased out)
- **Host**: `136.111.66.222:8123`
- **User**: `default`
- **Password**: GCP Secret Manager → `CLICKHOUSE_PASSWORD` (or hardcoded fallback in `scripts/migrate_ch_to_adx.py`). **Treat CH as read-only going forward.** Backup and source of truth until cutover is fully validated.

---

## 2. Local dev setup (for picking up cold)

```bash
# 1. Repo + venv
cd ~/Documents/mystuff/x/extrarepos/nova-manager
git checkout feature/adx-integration
poetry install

# 2. Azure auth (DefaultAzureCredential picks this up)
az login
az account set --subscription "Battlin Project"
az account show --query '{tenant:tenantId, sub:name}'  # should show tenant 1a27bdbf-... and "Battlin Project"

# 3. Postgres should be running on localhost:5432 (user-managed, not Docker)
# 4. `.env` should already exist with DATABASE_URL=postgresql://postgres@localhost:5432/nova_manager3
#    and ADX_CLUSTER_URI, ADX_TENANT_ID

# 5. Smoke test: query ADX as the logged-in user
poetry run python -c "
from azure.identity import DefaultAzureCredential
from azure.kusto.data import KustoClient, KustoConnectionStringBuilder
kcsb = KustoConnectionStringBuilder.with_azure_token_credential(
    'https://kresadxdev.centralindia.kusto.windows.net', DefaultAzureCredential())
r = KustoClient(kcsb).execute_query('org_test_db_check', 'raw_events | count')
print(list(r.primary_results[0]))
"
# Should print [{'Count': 0}] (or non-zero if a test just ran)
```

If `az login` is for a different tenant, ADX will return 401. Re-login with `--tenant 1a27bdbf-e6cc-4e33-85d2-e1c81bad930a`.

---

## 3. Code structure tour

### Service layer (ADX adapter)
- `nova_manager/service/analytics_service.py` — abstract `AnalyticsService` ABC.
- `nova_manager/service/adx_service.py` — ADX implementation (KustoClient + queued/inline ingestion). **See P0.**
- `nova_manager/service/clickhouse_service.py` — CH implementation (extends ABC).
- `nova_manager/service/analytics_factory.py` — `get_analytics_service(backend, database)` returns the right one per app.

### Query builders
- `nova_manager/components/metrics/query_builder.py` — SQL/ClickHouse.
- `nova_manager/components/metrics/kql_query_builder.py` — KQL for ADX.
- `nova_manager/components/metrics/query_builder_factory.py` — picks one per backend.

### Per-backend routing
- `nova_manager/components/auth/models.py:36-41` — `App.analytics_backend` column. `default=lambda: NOVA_DEFAULT_ANALYTICS_BACKEND`, `server_default="clickhouse"`. Existing rows are untouched; new apps inherit the env-var default.
- `nova_manager/components/auth/dependencies.py:23-33` `_lookup_analytics_backend(app_id)` — looks up the app's backend on every request, sets `auth.analytics_backend`.
- `nova_manager/components/metrics/events_controller.py` — `EventsController(org_id, app_id, analytics_backend)`. Every method branches on `self.analytics_backend == "adx"`. **Many `if backend == "adx"` branches — high risk for code drift; audit when adding new metric types.**
- `nova_manager/api/metrics/router.py` — wires controllers and analytics_service per backend. Several endpoints. **Three of them (compute, ingest_business_data, list_business_data_schema) are now `def` not `async def` after the P0 partial fix.**

### Config (env-driven)
- `nova_manager/core/config.py:5` `load_dotenv(..., override=False)` — **important:** shell/subprocess env wins over `.env`. Was `True` before; that bug was silently writing tests to the dev DB.
- `nova_manager/core/config.py:20-29` — ADX/Nova env vars. The relevant knobs:
  - `ADX_CLUSTER_URI`, `ADX_TENANT_ID`, `ADX_DATABASE` — cluster + per-app override.
  - `ADX_INGEST_MODE` — `queued` (default, prod) or `inline` (tests, synchronous).
  - `NOVA_DEFAULT_ANALYTICS_BACKEND` — default for newly-created apps; default `clickhouse`.

### Database (Postgres) migration
- `alembic/versions/8ba9bc07debf_add_analytics_backend_to_apps.py` — adds the column.

### Scripts
- `scripts/migrate_ch_to_adx.py` — CH→ADX migration (export + ingest + verify phases). **CH ops are SELECT-only** (already audited). ADX ops drop+recreate tables — **destructive on ADX**, fine for first migration, NOT what you want for drift backfill (see §5).
- `scripts/verify_ch_adx_migration.py` — row-count + sample-data + metric-query comparison between CH and ADX for the Batlin app.

### Tests
- `tests/` — Nova unit tests. ~313 collected; ~312 pass. Pre-existing `test_filter_like` fails (see P3).
- `scripts/integration/test_adx_kql.py` — 47-check ADX integration test against the real cluster. Uses `.ingest inline` to bypass queued-ingestion latency.
- `tests/e2e/` lives in the **overwatch** repo, not here. See §4.

---

## 4. Test infrastructure

### Overwatch E2E (`tests/e2e/` in `Krafton-ESports-python-backend`)

`tests/e2e/conftest.py` provisions a real Nova + wallet service for the session, then runs overwatch through its TestClient against them.

**Two modes:**

**Subprocess mode (default).** Conftest spawns Nova as a uvicorn subprocess with env vars set for ADX. Used for CI / fast iteration. Wipes `nova_manager_e2e` Postgres at session start. The Nova subprocess gets these env vars set explicitly:
```
DATABASE_URL=postgresql://postgres@localhost:5432/nova_manager_e2e
ADX_CLUSTER_URI=https://kresadxdev.centralindia.kusto.windows.net
ADX_TENANT_ID=1a27bdbf-e6cc-4e33-85d2-e1c81bad930a
ADX_DATABASE=org_test_db_check
ADX_INGEST_MODE=inline
NOVA_DEFAULT_ANALYTICS_BACKEND=adx
JWT_SECRET_KEY=e2e-test-secret
```

**External Nova mode.** Set `NOVA_API_BASE_URL` to a running Nova. Conftest skips the spawn, wipes nothing, points overwatch at the URL. You're responsible for starting Nova with the right env vars before running tests. Closer to prod topology (Nova as its own service, overwatch as a consumer).

```bash
# From the overwatch repo:
.venv/bin/python -m pytest tests/e2e/test_analytics.py -v   # subprocess mode
NOVA_API_BASE_URL=http://localhost:8000 .venv/bin/python -m pytest tests/e2e/ -v   # external Nova mode
```

### Overwatch nova_client timeout
`overwatch/integrations/nova/client.py` and `overwatch/core/config.py` — `NOVA_API_TIMEOUT` env var (default 10s, conftest bumps to 60s). Replaced all 8 hardcoded `httpx.Client(timeout=10.0)` calls.

### The ADX_INGEST_MODE=inline trick
Without it, ADX queued ingestion takes ~5 minutes before rows are queryable. Tests would all time out. Inline mode uses `.ingest inline into table T with (format='multijson') <| {...}` which is a synchronous mgmt-plane command — rows queryable immediately. Subject to a per-command payload size cap (~1MB practical limit), so the inline path is only safe for low-volume test writes. Prod stays on queued.

Implementation: `ADXService.insert_rows` branches on `ADX_INGEST_MODE` at `nova_manager/service/adx_service.py:55-62`. The inline helper is `_insert_rows_inline` at lines 81-94.

---

## 5. Issues to fix, in priority order

### P0 — Kusto SDK has no HTTP-level timeout (production robustness blocker)

**Where:** `nova_manager/service/adx_service.py`. `KustoClient` (from `azure-kusto-data`) uses `requests` under the hood with no HTTP read timeout configured.

**Symptom:** When ADX half-closes a TCP connection (transient network blip, throttling on the dev SKU, token edge-case, cluster restart), the SDK's underlying `socket.read()` blocks indefinitely. Each blocked call sits on a FastAPI/anyio threadpool worker. After enough requests pile up, Nova goes silent — every subsequent request times out at the client.

**Reproduce:** From overwatch repo:
```bash
.venv/bin/python -m pytest tests/e2e/test_analytics_excel.py -v
```
First 6-16 tests pass; once any Kusto query trips, you'll see "Cannot reach Nova API: timed out" for everything that follows. `lsof -p <nova_pid>` will show TCP connections to `135.235.250.108:https` in `CLOSED` state — that's the smoking gun (ADX closed them, SDK hasn't noticed).

**Already done (partial mitigations on this branch):**
- `nova_manager/service/adx_service.py:18-31` — `ClientRequestProperties.request_timeout_option_name` set to `timedelta(seconds=30)` for queries, `timedelta(minutes=1)` for mgmt commands. This is **server-side** — the cluster aborts and responds, *if it can*. Doesn't help when the underlying socket is wedged.
- `nova_manager/api/metrics/router.py:81, 200, 226` — `compute_metric`, `ingest_business_data`, `list_business_data_schema` switched from `async def` to `def`. So they run in the threadpool instead of blocking the event loop. Limits blast radius (Nova's accept loop survives), doesn't unstick individual workers.

**Real fix options:**

1. **Custom `requests.Session` with HTTP read timeout** injected into `KustoClient`. The SDK constructs its session internally — you'd need to monkey-patch or use `KustoClient._session = my_session` post-construction (private API, version-fragile). Set `session.adapters` with `urllib3.Retry` + `HTTPAdapter` with a `timeout`. Smallest surgical fix.
2. **Switch to async Kusto client** (`from azure.kusto.data.aio import KustoClient`). Make calling endpoints `async def` + `await result`. The async client has proper cancellation. More invasive but the right shape long-term.
3. **`concurrent.futures` wrapper** with `future.result(timeout=...)`. Caller wakes up, but the underlying thread is still leaked until the SDK eventually fails. Don't do this — slow leak under sustained errors.

Recommend option 1 to ship fast, option 2 as the proper landing.

**Acceptance criteria:** `tests/e2e/test_analytics_excel.py` runs to completion. Individual tests may pass or fail, but **no cascade** of "Cannot reach Nova API: timed out" — failures stay isolated to specific tests.

### P1 — Other `async def` endpoints calling sync I/O

55 `async def` endpoints in `nova_manager/api/`. Most don't use `await`, meaning they're `async def` for no reason and block the event loop on any sync I/O. Same root cause as P0's partial fix, different code paths.

**Audit script:**
```bash
# List async defs in nova/api/ that don't contain an await
for f in $(grep -rlE "^async def" nova_manager/api/); do
  python -c "
import ast, sys
tree = ast.parse(open('$f').read())
for node in ast.walk(tree):
    if isinstance(node, ast.AsyncFunctionDef):
        awaits = [n for n in ast.walk(node) if isinstance(n, ast.Await)]
        if not awaits:
            print('$f:%d %s' % (node.lineno, node.name))
"
done
```

Routers to audit:
```
nova_manager/api/feature_flags/router.py
nova_manager/api/recommendations/router.py
nova_manager/api/experiences/router.py
nova_manager/api/user_experience/router.py
nova_manager/api/users/router.py
nova_manager/api/personalisations/router.py
nova_manager/api/invitations/router.py
nova_manager/api/segments/router.py
nova_manager/api/auth/router.py
nova_manager/api/metrics/router.py  # already partially audited
nova_manager/api/simulations/router.py  # run_simulation is correctly `def`
```

**Rule:** if it doesn't `await`, it shouldn't be `async`. Drop the `async` keyword — FastAPI runs sync endpoints in a threadpool, isolating blocking calls.

### P2 — Dev SKU ADX cluster throttles under sequential load

`kresadxdev` is a dev/basic SKU. Sequential queries from one test session (each writing + reading business_metrics) push the cluster into "close connection mid-flight." Even with P0 fixed, you'll see ~5-10% Kusto errors on tests of this shape unless you bump the SKU.

Also — **prod uses `QueuedIngestClient` with default batching policy** (`adx_service.py:42-47`). That means events take ~5 minutes to be queryable in prod. Not a crash bug, but a real UX gap: send an event, dashboard shows nothing for 5 minutes. At "millions of users," consider:
- `ManagedStreamingIngestClient` — hybrid (streaming for small writes, queued for batches). Microsoft-recommended pattern. Requires cluster + db + table streaming policy enabled.
- Aggressive batching policy (`MaximumBatchingTimeSpan = 30s` instead of 5m). Cheaper, looser.

**Retry caveat:** do not add retries to `ADXService` until P0's HTTP timeout is in. Retries on a hanging call multiply the hang.

### P3 — Pre-existing bug: `test_filter_like`

`tests/test_compute_queries.py::TestCountQuery::test_filter_like` fails because `LIKE` isn't in `ALLOWED_OPS` in `nova_manager/components/metrics/query_builder.py` (around line 552, search for `ALLOWED_OPS`). Unrelated to ADX. Either add `LIKE` to `ALLOWED_OPS` and implement, or delete the test.

---

## 6. Operational tasks not done yet

### Drift backfill: ~14K CH rows not in ADX (Batlin app)

As of 2026-06-03:

| Table | ClickHouse | ADX | Delta |
|---|---:|---:|---:|
| `raw_events` | 10,814 | 8,436 | 2,378 |
| `event_props` | 26,397 | 20,739 | 5,658 |
| `user_profile_props` | 7,768 | 5,849 | 1,919 |
| `user_experience` | 18,092 | 14,318 | 3,774 |
| `business_metrics` | 128 | 128 | 0 |
| **Total** | **63,199** | **49,470** | **13,729** |

These are events that went into CH between May 17 (when the original migration ran) and the Batlin ADX cutover date. They need to be copied across before CH can be retired.

**Constraint:** ClickHouse ops are READ-ONLY. Do not INSERT/UPDATE/DELETE/ALTER/DROP/TRUNCATE on CH. CH is the backup/fallback until ADX is fully trusted. SELECT only.

**Approach (incremental, idempotent):**
1. For each table, find `max(server_ts)` (or `max(client_ts)`, or `max(assigned_at)` for `user_experience`) in ADX. That's the watermark.
2. SELECT rows from CH where `ts > watermark`.
3. INSERT into ADX (append, no DROP). Inline ingest is fine for ~14K rows total.
4. Verify counts.

The existing `scripts/migrate_ch_to_adx.py` uses drop-and-recreate on ADX — **don't use it for drift backfill** (would wipe the 49K ADX rows). Write a separate script or add an `--incremental` flag.

### Smoke user cleanup (deferred, low priority)

Local `nova_manager3` has 5 `smoke_HEX@example.com` users from May 3-5 leaving 16 dependent rows across `feature_flags`, `metrics`, `segments`, `simulations`, `users`. The handoff doc mentioned `adx-smoke@test.internal` but **that user does not exist** in either local or real-prod DBs (handoff was wrong about the exact email). The 5 smoke users + dependents could be cleaned but aren't blocking anything.

Real prod Postgres (GCP Cloud SQL) hasn't been checked — would need `cloud-sql-proxy` running. Not urgent.

---

## 7. What this session fixed

Commits on `feature/adx-integration` (newest first):

- `317a158` `docs: ADX integration follow-ups` — this doc.
- `225ce93` `fix: set Kusto server timeout to prevent threadpool starvation on stuck queries` — partial P0.
- `adce8d2` `fix: make Kusto-touching metrics endpoints sync to avoid blocking event loop` — partial P0.
- `2de7d92` `fix: strip db prefix from table name in business-data/schema KQL` — schema endpoint was passing `org_xxx.business_metrics` as a KQL identifier (invalid in KQL — needs bare `business_metrics`), then silently swallowing the error and returning `[]`. Fixed both: strip the prefix, log the error instead of swallowing.
- `c2309a1` `fix: dotenv override=False so shell/subprocess env wins over .env` — `load_dotenv(override=True)` was silently clobbering env vars passed to subprocesses. Tests had been writing to `nova_manager3` (dev DB), not the test DB. Switched to `override=False` (12-factor standard: shell wins over file).
- `faa7e37` `chore: ignore scripts/migration_data/ exports`
- `a434793` `docs: ADX service principal request and data notes`
- `d70c8ce` `scripts: ClickHouse to ADX migration and verification`
- `884a9ec` `feat: NOVA_DEFAULT_ANALYTICS_BACKEND sets backend for new apps` — env-var default; lets overwatch tests configure Nova without poking at Nova's Postgres directly.
- `40af54f` `feat: add ADX_INGEST_MODE=inline for synchronous test ingestion` — see §4.

Overwatch commits on `jeera/analytics`:
- `d502199` `test: bump conftest timeouts and fail loudly on app-create errors`
- `ac8d80d` `feat: NOVA_API_TIMEOUT env var for nova_client httpx timeout`
- `bba9db9` `test: NOVA_API_BASE_URL skips subprocess, uses external Nova` — Shape A.
- `8705abe` `test: e2e conftest points Nova at ADX instead of ClickHouse`

---

## 8. E2E test status snapshot

Against ADX with current fixes (2026-06-03):

| File | Pass | Fail | Notes |
|---|---:|---:|---|
| `tests/e2e/test_analytics.py` | 12 | 0 | Reliable. Simulations CRUD, RBAC, schema, marketing-spend ingest+query. |
| `tests/e2e/test_analytics_excel.py` | 6-16 | 8-18 | Variable. First cascade trigger after the P0 bug fires. Fix P0 to stabilise. |
| `tests/e2e/test_analytics_simulations.py` | 0 | 9 | All cascade-fail after excel suite trips. |
| `tests/e2e/test_analytics_wallet_pipeline.py` | 0 | 12 | Same cascade. |
| `tests/e2e/test_analytics.py` (unit-style tests at root of `tests/`) | 312 | 1 | Pre-existing `test_filter_like` fails (P3). |

The 12 reliable E2E tests cover the core feature surface. The remaining 30 will green once P0 is fixed.

---

## 9. Glossary

- **ADX / Kusto** — Azure Data Explorer. Microsoft's columnar analytics DB. Replaces ClickHouse.
- **KQL** — Kusto Query Language. Pipe-based: `table | where x > 1 | summarize count() by y`.
- **Inline ingest** — `.ingest inline into table T with (format='multijson') <| {...}`. Synchronous mgmt-plane command. Used only in tests.
- **Queued ingest** — `QueuedIngestClient.ingest_from_stream(...)`. Async, ~5 min latency before queryable. Used in prod.
- **Streaming ingest** — `ManagedStreamingIngestClient`. Hybrid, low-latency. Not currently used; relevant for prod scale.
- **Per-app database** — Each org+app combo gets its own ADX database `org_{org}_app_{app}`. `ADX_DATABASE` env var overrides this for testing (everything points at `org_test_db_check`).
- **DefaultAzureCredential** — Azure SDK auth chain. Order: env vars → managed identity → `az login` cache → interactive. In Cloud Run, env vars (`AZURE_CLIENT_ID`/`SECRET`/`TENANT_ID`); locally, `az login`.
- **Cutover** — Moving an app from ClickHouse to ADX. Currently per-app via `apps.analytics_backend`. Batlin done; others pending.

---

## 10. Things to double-check first when picking this up

1. **Re-fetch and confirm the branch:** `git checkout feature/adx-integration && git pull`. Memory says we pushed everything, but verify.
2. **Re-check file:line refs in this doc** — code moves.
3. **Re-confirm cluster state:** `org_test_db_check` should have 5 tables with 0 rows. Batlin db should still have ~49K rows (no big drift since this doc was written, probably).
4. **Run a smoke test** before assuming everything works: `tests/e2e/test_analytics.py::test_run_simulation` should pass.
5. **Read the memories:** `~/.claude/projects/-Users-pranaypandit-Documents-mystuff-x-extrarepos-nova-manager/memory/MEMORY.md` and the linked files.
