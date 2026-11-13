"""POST /api/v1/metrics/compute/ must not stall the API while ClickHouse works.

Regression for 2026-11-13: compute was an async handler making a blocking ClickHouse call, so
every 5-10 s query froze the instance's event loop. PB's ~12 KPI calls ran one after another,
and the app's track-events and PB's own login waited behind them.
"""

import asyncio
import time
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from nova_manager.api.metrics import router as metrics_module
from nova_manager.components.auth.dependencies import require_app_context
from nova_manager.components.metrics.query_builder import QueryBuilder
from nova_manager.core.enums import UserRole
from nova_manager.core.security import AuthContext
from nova_manager.database.session import get_db
from nova_manager.middlewares.exceptions import ExceptionMiddleware

ORG = "11111111-1111-1111-1111-111111111111"
APP = "22222222-2222-2222-2222-222222222222"
COMPUTE = "/api/v1/metrics/compute/"
PB_DISTINCT_LOGINS = {
    "type": "count",
    "config": {
        "event_name": "app.login_completed", "distinct": True,
        "time_range": {"start": "2026-11-12 18:30:00", "end": "2026-11-13 18:30:00"},
        "granularity": "none", "group_by": [], "filters": {},
    },
}


class BlockingClickHouse:
    """Stands in for ClickHouseService: run_query blocks the calling thread, like clickhouse_connect."""

    def __init__(self, delay=0.0, rows=None, error=None):
        self.delay, self.error = delay, error
        self.rows = rows if rows is not None else [{"period": "1970-01-01 00:00:00", "value": 42}]
        self.queries: list[str] = []
        self.settings: list[dict | None] = []

    def run_query(self, query, parameters=None, settings=None):
        self.queries.append(query)
        self.settings.append(settings)
        time.sleep(self.delay)
        if self.error:
            raise self.error
        return self.rows


def _app(clickhouse, monkeypatch, with_auth=True) -> FastAPI:
    monkeypatch.setattr(metrics_module, "ClickHouseService", lambda: clickhouse)
    app = FastAPI()
    app.add_middleware(ExceptionMiddleware)
    app.include_router(metrics_module.router, prefix="/api/v1/metrics")

    @app.get("/ping")
    async def ping():  # any other request served by the same instance
        return {"ok": True}

    if with_auth:
        app.dependency_overrides[require_app_context] = lambda: AuthContext(
            auth_user_id="u-1", organisation_id=ORG, app_id=APP, email="pb@example.com", role=UserRole.ADMIN
        )
    app.dependency_overrides[get_db] = lambda: MagicMock()
    return app


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://nova")


@pytest.mark.asyncio
async def test_slow_compute_does_not_hold_up_other_requests_on_the_same_instance(monkeypatch):
    app = _app(BlockingClickHouse(delay=0.6), monkeypatch)
    async with _client(app) as c:
        started = time.perf_counter()
        compute = asyncio.create_task(c.post(COMPUTE, json=PB_DISTINCT_LOGINS))
        await asyncio.sleep(0.1)  # compute is now waiting on ClickHouse
        ping = await c.get("/ping")
        ping_done = time.perf_counter() - started
        assert (await compute).status_code == 200
    assert ping.status_code == 200
    # Blocked event loop: the ping can only finish after the 0.6 s query, i.e. >= 0.6 s.
    assert ping_done < 0.4, f"ping waited {ping_done:.2f}s behind a ClickHouse query"


@pytest.mark.asyncio
async def test_parallel_compute_calls_overlap_instead_of_queueing(monkeypatch):
    """PB now sends its KPI calls in parallel; they must actually run side by side."""
    clickhouse = BlockingClickHouse(delay=0.4)
    app = _app(clickhouse, monkeypatch)
    async with _client(app) as c:
        started = time.perf_counter()
        responses = await asyncio.gather(*(c.post(COMPUTE, json=PB_DISTINCT_LOGINS) for _ in range(4)))
        elapsed = time.perf_counter() - started
    assert [r.status_code for r in responses] == [200] * 4
    assert len(clickhouse.queries) == 4
    assert elapsed < 1.0, f"4 x 0.4 s queries took {elapsed:.2f}s (one after another would be 1.6 s)"


@pytest.mark.asyncio
async def test_compute_returns_clickhouse_rows_for_the_callers_own_app(monkeypatch):
    rows = [{"period": "1970-01-01 00:00:00", "value": 1234}]
    clickhouse = BlockingClickHouse(rows=rows)
    async with _client(_app(clickhouse, monkeypatch)) as c:
        response = await c.post(COMPUTE, json=PB_DISTINCT_LOGINS)
    assert response.status_code == 200
    assert response.json() == rows
    [sql] = clickhouse.queries
    assert f"FROM {QueryBuilder(ORG, APP)._raw_events_table_name()} AS e" in sql
    assert "uniqExact(e.user_id) AS value" in sql


@pytest.mark.asyncio
async def test_clickhouse_failure_is_still_a_500_carrying_the_reason(monkeypatch):
    error = RuntimeError("Code: 241. DB::Exception: Memory limit (total) exceeded (MEMORY_LIMIT_EXCEEDED)")
    async with _client(_app(BlockingClickHouse(error=error), monkeypatch)) as c:
        response = await c.post(COMPUTE, json=PB_DISTINCT_LOGINS)
    assert response.status_code == 500
    assert "MEMORY_LIMIT_EXCEEDED" in response.text


@pytest.mark.asyncio
async def test_compute_without_credentials_is_refused_and_runs_no_query(monkeypatch):
    clickhouse = BlockingClickHouse()
    async with _client(_app(clickhouse, monkeypatch, with_auth=False)) as c:
        response = await c.post(COMPUTE, json=PB_DISTINCT_LOGINS)
    assert response.status_code in (401, 403)
    assert clickhouse.queries == []


# ── POST /compute-batch/: PB's whole KPI page in one request ─────────────

BATCH = "/api/v1/metrics/compute-batch/"


def _count(event_name, **config):
    return {"type": "count", "config": {
        "event_name": event_name, "distinct": False,
        "time_range": {"start": "2026-11-12 18:30:00", "end": "2026-11-13 18:30:00"},
        "granularity": "none", "group_by": [], "filters": {}, **config,
    }}


class PerEventClickHouse(BlockingClickHouse):
    """Answers each query with the number of its event, so results can be matched to requests."""

    def __init__(self, delay=0.0, values=None, failing=()):
        super().__init__(delay=delay)
        self.values, self.failing = values or {}, set(failing)
        self.running, self.max_running = 0, 0
        self._lock = __import__("threading").Lock()

    def run_query(self, query, parameters=None, settings=None):
        with self._lock:
            self.queries.append(query)
            self.settings.append(settings)
            self.running += 1
            self.max_running = max(self.max_running, self.running)
        try:
            time.sleep(self.delay)
            event = next(e for e in list(self.values) + list(self.failing) if f"e.event_name = '{e}'" in query)
            if event in self.failing:
                raise RuntimeError(f"Code: 241. MEMORY_LIMIT_EXCEEDED while computing {event}")
            return [{"period": "1970-01-01 00:00:00", "value": self.values[event]}]
        finally:
            with self._lock:
                self.running -= 1


@pytest.mark.asyncio
async def test_batch_returns_every_metric_in_request_order(monkeypatch):
    clickhouse = PerEventClickHouse(values={"app.installed": 11, "app.login_completed": 22, "tournament.created": 33})
    body = {"metrics": [_count("tournament.created"), _count("app.installed"), _count("app.login_completed")]}
    async with _client(_app(clickhouse, monkeypatch)) as c:
        response = await c.post(BATCH, json=body)
    assert response.status_code == 200
    assert [(r["status"], r["data"][0]["value"]) for r in response.json()["results"]] == [(200, 33), (200, 11), (200, 22)]


@pytest.mark.asyncio
async def test_one_failing_metric_does_not_fail_the_rest_of_the_batch(monkeypatch):
    clickhouse = PerEventClickHouse(values={"app.installed": 11, "tournament.joined": 44}, failing={"incentive.earned"})
    body = {"metrics": [_count("app.installed"), _count("incentive.earned"), _count("tournament.joined")]}
    async with _client(_app(clickhouse, monkeypatch)) as c:
        response = await c.post(BATCH, json=body)
    assert response.status_code == 200
    first, failed, last = response.json()["results"]
    assert (first["status"], first["data"][0]["value"]) == (200, 11)
    assert failed["status"] == 500 and "MEMORY_LIMIT_EXCEEDED" in failed["error"] and "data" not in failed
    assert (last["status"], last["data"][0]["value"]) == (200, 44)


@pytest.mark.asyncio
async def test_batch_metrics_run_side_by_side(monkeypatch):
    clickhouse = PerEventClickHouse(delay=0.4, values={f"kpi.{i}": i for i in range(4)})
    async with _client(_app(clickhouse, monkeypatch)) as c:
        started = time.perf_counter()
        response = await c.post(BATCH, json={"metrics": [_count(f"kpi.{i}") for i in range(4)]})
        elapsed = time.perf_counter() - started
    assert [r["status"] for r in response.json()["results"]] == [200] * 4
    assert elapsed < 1.0, f"4 x 0.4 s metrics took {elapsed:.2f}s (one after another would be 1.6 s)"


@pytest.mark.asyncio
async def test_batch_never_runs_more_than_four_clickhouse_queries_at_once(monkeypatch):
    """The ClickHouse VM has 2 vCPUs; a 25-metric dashboard must not fire 25 queries at once."""
    clickhouse = PerEventClickHouse(delay=0.2, values={f"kpi.{i}": i for i in range(8)})
    async with _client(_app(clickhouse, monkeypatch)) as c:
        response = await c.post(BATCH, json={"metrics": [_count(f"kpi.{i}") for i in range(8)]})
    assert [r["status"] for r in response.json()["results"]] == [200] * 8
    assert clickhouse.max_running == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("size,status", [(0, 422), (1, 200), (25, 200), (26, 422)])
async def test_batch_size_limits(monkeypatch, size, status):
    clickhouse = PerEventClickHouse(values={"app.installed": 1})
    async with _client(_app(clickhouse, monkeypatch)) as c:
        response = await c.post(BATCH, json={"metrics": [_count("app.installed")] * size})
    assert response.status_code == status
    assert len(clickhouse.queries) == (size if status == 200 else 0)


@pytest.mark.asyncio
async def test_unknown_metric_type_rejects_the_whole_batch_before_any_query(monkeypatch):
    clickhouse = PerEventClickHouse(values={"app.installed": 1})
    body = {"metrics": [_count("app.installed"), {"type": "median", "config": {}}]}
    async with _client(_app(clickhouse, monkeypatch)) as c:
        response = await c.post(BATCH, json=body)
    assert response.status_code == 422
    assert clickhouse.queries == []


@pytest.mark.asyncio
async def test_invalid_time_range_fails_only_that_metric_and_runs_no_query_for_it(monkeypatch):
    clickhouse = PerEventClickHouse(values={"app.installed": 7})
    bad = _count("app.registration_completed", time_range={"start": "soon", "end": "2026-11-13 18:30:00"})
    async with _client(_app(clickhouse, monkeypatch)) as c:
        response = await c.post(BATCH, json={"metrics": [bad, _count("app.installed")]})
    failed, ok = response.json()["results"]
    assert failed["status"] == 500 and "Invalid start date format" in failed["error"]
    assert (ok["status"], ok["data"][0]["value"]) == (200, 7)
    assert len(clickhouse.queries) == 1


@pytest.mark.asyncio
async def test_unknown_segment_is_a_404_for_that_metric_only(monkeypatch):
    class NoSegments:
        def __init__(self, db):
            pass

        def get_by_pid(self, pid):
            return None

    monkeypatch.setattr(metrics_module, "SegmentsCRUD", NoSegments)
    clickhouse = PerEventClickHouse(values={"app.installed": 5})
    body = {"metrics": [_count("app.login_completed", segment_ids=["seg-gone"]), _count("app.installed")]}
    async with _client(_app(clickhouse, monkeypatch)) as c:
        response = await c.post(BATCH, json=body)
    missing, ok = response.json()["results"]
    assert missing == {"status": 404, "error": "Segment seg-gone not found"}
    assert (ok["status"], ok["data"][0]["value"]) == (200, 5)


@pytest.mark.asyncio
async def test_batch_without_credentials_is_refused_and_runs_no_query(monkeypatch):
    clickhouse = PerEventClickHouse(values={"app.installed": 1})
    async with _client(_app(clickhouse, monkeypatch, with_auth=False)) as c:
        response = await c.post(BATCH, json={"metrics": [_count("app.installed")]})
    assert response.status_code in (401, 403)
    assert clickhouse.queries == []


@pytest.mark.asyncio
async def test_batch_queries_only_the_callers_own_app(monkeypatch):
    clickhouse = PerEventClickHouse(values={"app.installed": 1, "app.login_completed": 2})
    async with _client(_app(clickhouse, monkeypatch)) as c:
        await c.post(BATCH, json={"metrics": [_count("app.installed"), _count("app.login_completed")]})
    own_table = QueryBuilder(ORG, APP)._raw_events_table_name()
    assert len(clickhouse.queries) == 2
    assert all(f"FROM {own_table} AS e" in q for q in clickhouse.queries)


@pytest.mark.asyncio
async def test_parallel_single_computes_never_run_more_than_four_clickhouse_queries_at_once(monkeypatch):
    """PB fires 8 /compute/ calls at once; each instance must still cap ClickHouse at 4, as batches are."""
    clickhouse = PerEventClickHouse(delay=0.2, values={f"kpi.{i}": i for i in range(8)})
    async with _client(_app(clickhouse, monkeypatch)) as c:
        responses = await asyncio.gather(*(c.post(COMPUTE, json=_count(f"kpi.{i}")) for i in range(8)))
    assert [r.json()[0]["value"] for r in responses] == list(range(8))
    assert clickhouse.max_running == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("path,body", [
    (COMPUTE, PB_DISTINCT_LOGINS),
    (BATCH, {"metrics": [PB_DISTINCT_LOGINS, PB_DISTINCT_LOGINS]}),
])
async def test_metric_queries_are_time_limited_so_one_cannot_hold_a_slot_for_minutes(monkeypatch, path, body):
    clickhouse = BlockingClickHouse()
    async with _client(_app(clickhouse, monkeypatch)) as c:
        assert (await c.post(path, json=body)).status_code == 200
    assert clickhouse.settings and all(s == {"max_execution_time": 60} for s in clickhouse.settings)


@pytest.mark.asyncio
async def test_a_running_batch_does_not_hold_up_other_requests(monkeypatch):
    app = _app(PerEventClickHouse(delay=0.6, values={"app.installed": 1}), monkeypatch)
    async with _client(app) as c:
        started = time.perf_counter()
        batch = asyncio.create_task(c.post(BATCH, json={"metrics": [_count("app.installed")]}))
        await asyncio.sleep(0.1)
        ping = await c.get("/ping")
        ping_done = time.perf_counter() - started
        assert (await batch).status_code == 200
    assert ping.status_code == 200
    assert ping_done < 0.4, f"ping waited {ping_done:.2f}s behind a batch"
