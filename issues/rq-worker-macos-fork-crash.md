# RQ Worker Crash on macOS (SIGABRT on fork)

## Problem

The RQ (Redis Queue) worker crashes with `signal 6` (SIGABRT) when processing jobs on macOS. The work-horse process terminates unexpectedly during fork.

**Error from `rq info`:**
```
Work-horse terminated unexpectedly; waitpid returned 6 (signal 6)
```

## Impact

- ALL event-based async jobs fail: `track-event`, `track-events`, `track_user_profile`, `track_user_experience`
- No events land in ClickHouse `raw_events` / `event_props` tables
- Metrics that depend on event data return empty results
- Business data ingestion (`POST /business-data/`) is NOT affected — it writes directly to ClickHouse without going through RQ

## Root Cause

macOS has `fork()` safety restrictions since Catalina. When the RQ worker forks a child process (work-horse) to execute a job, libraries that hold resources across fork boundaries (e.g., `clickhouse-connect`, `psycopg2`, database connections) can trigger `SIGABRT`.

The ClickHouseService uses lazy initialization (`_client = None`, created on first use), which should work — but the SQLAlchemy/psycopg2 connection pool from `db_session()` in `EventsController` methods may be the issue, as these connections are created before the fork.

## Reproduction

```bash
# Start ClickHouse, PostgreSQL, Redis locally
docker compose up -d

# Start worker
rq worker --url redis://localhost:6379/0

# Track an event via API → worker picks up job → SIGABRT
curl -X POST http://localhost:8080/api/v1/metrics/track-event/ \
  -H "Authorization: Bearer <sdk_token>" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "event_name": "test", "event_data": {}, "timestamp": "2026-01-01T00:00:00Z"}'
```

## Possible Fixes

1. **Set `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES`** before starting worker (macOS workaround)
2. **Use `--worker-class rq.SimpleWorker`** which doesn't fork (runs jobs in-process)
3. **Ensure connections are created lazily after fork** — audit `EventsController` methods to not import/initialize DB connections at module level
4. **Switch to a threading-based worker** (e.g., RQ with `--worker-class rq.worker.SimpleWorker`)

## Workaround for Local Testing

```bash
# Option 1: Disable fork safety (macOS only)
OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES rq worker --url redis://localhost:6379/0

# Option 2: Use SimpleWorker (no fork)
rq worker --worker-class rq.SimpleWorker --url redis://localhost:6379/0
```

## Observed During

Integration test run on 2026-05-03. All 155 events tracked via API returned 200, but 0 events landed in ClickHouse because every worker job failed with SIGABRT.
