# ADX integration: follow-ups

Captured at the end of the session on 2026-06-03. Test infrastructure is in place and a baseline of E2E tests pass; the issues below are the remaining work to close out the cutover.

## P0 — Kusto SDK has no HTTP-level timeout (production robustness)

**Where:** `nova_manager/service/adx_service.py`. `ADXService.run_query` / `execute` / `_insert_rows_inline` use `KustoClient` from `azure-kusto-data`. The SDK uses `requests` under the hood and does not expose an HTTP read timeout.

**Symptom:** When the ADX cluster half-closes a TCP connection (transient network blip, throttling on the dev SKU, or token edge-case), the SDK's underlying `socket.read()` blocks indefinitely. The blocked call sits on a FastAPI/anyio threadpool worker. After enough requests pile up, Nova goes silent — every subsequent request times out at the client. Reproduced in overwatch E2E: `test_analytics_excel.py` cascades into "Cannot reach Nova API: timed out" once any Kusto query hangs.

**Partial mitigations already applied (this branch):**
- `ClientRequestProperties.request_timeout_option_name = 30s` for queries, 60s for mgmt commands. The cluster will abort and respond, *if it can*. Does not help when the underlying TCP socket itself is wedged.
- `compute_metric`, `ingest_business_data`, `list_business_data_schema` switched from `async def` to `def` so they run in the threadpool instead of blocking the event loop. Limits blast radius (Nova's listen-accept loop survives), but doesn't unstick individual threads.

**Real fix options:**
1. **Inject a custom `requests.Session` with HTTP read timeout** into `KustoClient`. The SDK accepts a session via private API (subject to version change) — see `KustoClient._session`. Wrap once at client construction.
2. **Switch to the async Kusto client** (`azure-kusto-data.aio.KustoClient`) and make the calling endpoints `async def` + `await`. More invasive but the right shape; async clients have proper cancellation.
3. **Add an outer `concurrent.futures` wrapper** with a hard timeout (`future.result(timeout=...)`). Kills the *waiting* but the thread still leaks until the SDK eventually fails — slow leak under sustained errors.

Option 1 is the smallest surgical fix; option 2 is the right long-term shape.

**Smoke test for the fix:** run `tests/e2e/test_analytics_excel.py` against ADX. Without the HTTP timeout, ~6 tests pass and the rest cascade. With it, all pass or fail individually with fast 500s.

## P1 — `async def` endpoints elsewhere in `nova_manager/api/`

Same pattern as #3 above: any `async def` endpoint that calls sync I/O (Postgres, Kusto, requests) blocks the event loop. Audit the remaining routers:

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
```

Many of these are pure Postgres CRUD — fine while Postgres is fast and there's no contention, dangerous under load. Rule: if it doesn't `await`, it shouldn't be `async`.

## P2 — Dev SKU ADX cluster likely throttles under sequential E2E load

`kresadxdev` is a dev/basic SKU. Sequential queries from one test session (each writing+reading business_metrics) seem to push the cluster into a "close connection mid-flight" failure mode. Even with proper Nova-side timeouts, you'll see ~10-20% Kusto errors on tests of this shape unless you bump the SKU or add retry logic.

**Retry caveat:** do not add retries to `ADXService` until the HTTP timeout above is in. Retries on a hanging call multiply the hang.

## P3 — Pre-existing bug: `test_filter_like`

`tests/test_compute_queries.py::TestCountQuery::test_filter_like` fails because `LIKE` isn't in `ALLOWED_OPS` in `query_builder.py`. Unrelated to ADX, noted in handoff. Either add LIKE support or delete the test.

## What the session did fix (already on `feature/adx-integration`)

- `c2309a1` `fix: dotenv override=False so shell/subprocess env wins over .env` — `load_dotenv(override=True)` was clobbering env vars passed to subprocesses; tests were silently writing to the dev DB.
- `2de7d92` `fix: strip db prefix from table name in business-data/schema KQL` — endpoint passed `org_xxx.business_metrics` as a KQL identifier (invalid), silently swallowed the error, returned empty.
- `adce8d2` `fix: make Kusto-touching metrics endpoints sync to avoid blocking event loop` — three endpoints converted from `async def` to `def`.
- `225ce93` `fix: set Kusto server timeout to prevent threadpool starvation on stuck queries` — partial fix for P0, see above.
- `40af54f` `feat: add ADX_INGEST_MODE=inline for synchronous test ingestion` — tests no longer wait 5 min for queued ingest.
- `884a9ec` `feat: NOVA_DEFAULT_ANALYTICS_BACKEND sets backend for new apps` — env-var default for newly-created apps; lets overwatch tests configure Nova cleanly.

## E2E test status snapshot

Against ADX with current fixes:

| File | Pass | Fail | Notes |
|---|---:|---:|---|
| `tests/e2e/test_analytics.py` | 12 | 0 | Reliable. Covers simulations, RBAC, schema, marketing-spend ingest+query. |
| `tests/e2e/test_analytics_excel.py` | ~6–16 | ~8–18 | Variable; first cascade-trigger point. Fix P0 to stabilise. |
| `tests/e2e/test_analytics_simulations.py` | 0 | 9 | All cascade-fail after excel suite trips. |
| `tests/e2e/test_analytics_wallet_pipeline.py` | 0 | 12 | Same cascade. |

12 stable passing tests covers the core feature surface. The remaining ~30 tests are gated on P0.

## Test-infra changes (already on `jeera/analytics` in overwatch repo)

- `tests/e2e/conftest.py`: spawned Nova now configured for ADX (`ADX_CLUSTER_URI`, `ADX_DATABASE=org_test_db_check`, `ADX_INGEST_MODE=inline`, `NOVA_DEFAULT_ANALYTICS_BACKEND=adx`). No ClickHouse docker dependency.
- `NOVA_API_BASE_URL` env var: when set, conftest skips the subprocess spawn and points overwatch at an externally-running Nova. Closer to prod topology.
- `NOVA_API_TIMEOUT` env var in `overwatch/core/config.py` + `overwatch/integrations/nova/client.py`: all 8 hardcoded `httpx.Client(timeout=10.0)` replaced. Default still 10s for prod; conftest bumps to 60s.
