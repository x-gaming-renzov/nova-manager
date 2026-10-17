"""The background worker keeps up with event traffic.

Forking per job re-imported the app and reopened every connection around each ~0.15s job,
which capped the worker below launch traffic and let the event queue fall hours behind.
"""

import importlib.util
import sys
import threading
from pathlib import Path

import pytest

from nova_manager.service import clickhouse_service


def _load_run_worker():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_worker.py"
    spec = importlib.util.spec_from_file_location("run_worker", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(sys.platform == "win32", reason="rq cannot be imported without fork()")
def test_worker_runs_jobs_in_process_instead_of_forking_one_per_job():
    from redis import Redis
    from rq import Queue, SimpleWorker

    conn = Redis()  # lazy: nothing connects until a command runs
    worker = _load_run_worker().build_worker(Queue("default", connection=conn), conn)
    assert isinstance(worker, SimpleWorker)


@pytest.mark.skipif(sys.platform == "win32", reason="rq cannot be imported without fork()")
def test_a_pool_runs_several_in_process_workers_at_once():
    from redis import Redis
    from rq import SimpleWorker

    pool = _load_run_worker().build_pool("default", Redis(), 3)
    assert (pool.num_workers, pool.worker_class) == (3, SimpleWorker)


@pytest.mark.skipif(sys.platform == "win32", reason="rq cannot be imported without fork()")
@pytest.mark.parametrize("processes, uses_pool", [(1, False), (3, True)])
def test_the_pool_is_used_only_when_more_than_one_process_is_configured(monkeypatch, processes, uses_pool):
    run_worker = _load_run_worker()
    started = []

    class FakePool:
        def start(self, burst):
            started.append("pool")

    class FakeWorker:
        _stop_requested = True

        def work(self, burst, with_scheduler):
            started.append("worker")

    monkeypatch.setattr(run_worker, "WORKER_PROCESSES", processes)
    monkeypatch.setattr(run_worker, "build_pool", lambda *a: FakePool())
    monkeypatch.setattr(run_worker, "build_worker", lambda *a: FakeWorker())
    monkeypatch.setattr(run_worker, "start_health_server", lambda port: None)
    monkeypatch.setattr(run_worker, "configure_logging", lambda: None)
    monkeypatch.setattr(sys, "argv", ["run_worker.py"])
    with pytest.raises(SystemExit) as exit_:
        run_worker.main()
    assert started == (["pool"] if uses_pool else ["worker"])
    assert exit_.value.code == 0


@pytest.fixture
def fresh_clients(monkeypatch):
    created = []

    def fake_get_client():
        client = object()
        created.append(client)
        return client

    monkeypatch.setattr(clickhouse_service, "_get_client", fake_get_client)
    monkeypatch.setattr(clickhouse_service, "_local", threading.local())
    return created


def test_services_in_one_thread_reuse_a_single_clickhouse_client(fresh_clients):
    first = clickhouse_service.ClickHouseService().client
    second = clickhouse_service.ClickHouseService().client
    assert first is second
    assert len(fresh_clients) == 1


def test_each_thread_gets_its_own_client_because_a_session_refuses_concurrent_queries(fresh_clients):
    main_client = clickhouse_service.ClickHouseService().client
    seen = []
    t = threading.Thread(target=lambda: seen.append(clickhouse_service.ClickHouseService().client))
    t.start()
    t.join()
    assert seen[0] is not main_client


def test_a_forked_process_builds_a_new_client_rather_than_reusing_the_parents_sockets(
    fresh_clients, monkeypatch
):
    parent_client = clickhouse_service.ClickHouseService().client
    monkeypatch.setattr(clickhouse_service.os, "getpid", lambda: -1)
    assert clickhouse_service.ClickHouseService().client is not parent_client


class _RecordingClient:
    def __init__(self, fail_inserts=0):
        self.type_lookups = 0
        self.inserts = []
        self.fail_inserts = fail_inserts

    def create_insert_context(self, table, column_names):
        self.type_lookups += 1
        return type("Ctx", (), {"column_types": [f"type:{c}" for c in column_names]})()

    def insert(self, **kwargs):
        if self.fail_inserts:
            self.fail_inserts -= 1
            raise RuntimeError("Code: 16. No such column")
        self.inserts.append(kwargs)


@pytest.fixture
def recording_client(monkeypatch):
    client = _RecordingClient()
    monkeypatch.setattr(clickhouse_service, "_shared_client", lambda: client)
    monkeypatch.setattr(clickhouse_service, "_column_types", {})
    return client


def test_a_table_is_described_once_not_before_every_insert(recording_client):
    for _ in range(3):
        clickhouse_service.ClickHouseService().insert_rows("db.raw_events", [{"user_id": "u", "event_name": "e"}])
    assert recording_client.type_lookups == 1
    assert recording_client.inserts[-1]["column_types"] == ["type:user_id", "type:event_name"]


def test_a_different_column_set_gets_its_own_types(recording_client):
    service = clickhouse_service.ClickHouseService()
    service.insert_rows("db.raw_events", [{"user_id": "u"}])
    service.insert_rows("db.raw_events", [{"user_id": "u", "event_name": "e"}])
    assert recording_client.type_lookups == 2


def test_inserts_are_batched_by_the_server_and_still_wait_so_failures_raise(recording_client):
    clickhouse_service.ClickHouseService().insert_rows("db.raw_events", [{"user_id": "u"}])
    assert recording_client.inserts[0]["settings"] == {"async_insert": 1, "wait_for_async_insert": 1}


def test_a_failed_insert_raises_and_looks_the_types_up_again_in_case_the_schema_changed(recording_client):
    recording_client.fail_inserts = 1
    service = clickhouse_service.ClickHouseService()
    with pytest.raises(RuntimeError):
        service.insert_rows("db.raw_events", [{"user_id": "u"}])
    service.insert_rows("db.raw_events", [{"user_id": "u"}])
    assert recording_client.type_lookups == 2
    assert len(recording_client.inserts) == 1


def _assignment(experience_id):
    from types import SimpleNamespace

    return SimpleNamespace(
        user_id="nova-user", experience_id=experience_id, personalisation_id=None, personalisation_name=None,
        experience_variant_id=None, features={"f": 1}, evaluation_reason="default", assigned_at=None,
    )


def test_all_assignments_from_one_call_go_to_clickhouse_in_one_insert(recording_client):
    from nova_manager.components.metrics.events_controller import EventsController

    EventsController("org", "app").track_user_experiences([_assignment("e1"), _assignment("e2"), _assignment("e3")], "ext")
    assert len(recording_client.inserts) == 1
    assert [row[0] for row in recording_client.inserts[0]["data"]] == ["ext", "ext", "ext"]


def test_jobs_queued_before_batching_still_write_their_single_assignment(recording_client):
    from nova_manager.components.metrics.events_controller import EventsController

    EventsController("org", "app").track_user_experience(_assignment("e1"))
    assert len(recording_client.inserts) == 1
    assert recording_client.inserts[0]["data"][0][0] == "nova-user"


@pytest.mark.skipif(sys.platform == "win32", reason="rq cannot be imported without fork()")
@pytest.mark.asyncio
async def test_creating_many_assignments_enqueues_one_job_not_one_per_assignment(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    from nova_manager.components.user_experience import crud_async
    from nova_manager.components.user_experience.schemas import UserExperienceAssignment

    instances = [object(), object(), object()]
    db = MagicMock()
    db.commit = AsyncMock()
    db.execute = AsyncMock(side_effect=[
        MagicMock(scalars=lambda: MagicMock(all=lambda: [1, 2, 3])),  # INSERT ... RETURNING id
        MagicMock(scalars=lambda: MagicMock(all=lambda: instances)),  # reload the inserted rows
    ])
    queue = MagicMock()
    monkeypatch.setattr(crud_async, "QueueController", lambda: queue)
    assignments = [
        UserExperienceAssignment.model_construct(experience_id=f"e{i}", personalisation_id=None, personalisation_name=None,
                                                 experience_variant_id=None, features={}, evaluation_reason="default")
        for i in range(3)
    ]

    await crud_async.UserExperienceAsyncCRUD(db).bulk_create_user_experience_personalisations(
        "nova-user", "org", "app", assignments, external_user_id="ext"
    )

    queue.add_task.assert_called_once()
    func, batch = queue.add_task.call_args.args
    assert func.__name__ == "track_user_experiences" and batch == instances
    assert queue.add_task.call_args.kwargs == {"external_user_id": "ext"}


class _SchemaStore:
    """Stands in for Postgres: counts reads and writes of event schema rows."""

    def __init__(self):
        self.rows = {}
        self.reads = self.creates = self.updates = 0

    def crud(self, db):
        store = self

        class Crud:
            def get_events_schema(self, names, org, app):
                store.reads += 1
                return [r for r in store.rows.values() if r.event_name in names and r.app_id == app]

            def bulk_create(self, objs):
                store.creates += len(objs)
                for o in objs:
                    store.rows[(o.app_id, o.event_name)] = o

            def bulk_update(self, objs):
                store.updates += len(objs)

        return Crud()


@pytest.fixture
def schema_store(monkeypatch):
    import contextlib

    from nova_manager.components.metrics import events_controller as ec

    store = _SchemaStore()
    monkeypatch.setattr(ec, "db_session", lambda: contextlib.nullcontext(object()))
    monkeypatch.setattr(ec, "EventsSchemaCRUD", store.crud)
    monkeypatch.setattr(ec, "flag_modified", lambda obj, attr: None)
    monkeypatch.setattr(ec, "_known_schema_keys", {})
    monkeypatch.setattr(ec.EventsController, "push_to_clickhouse", lambda self, raw, props: store.__dict__.setdefault("pushed", []).append(raw))
    return store


def _track(app="app", **event_data):
    from nova_manager.components.metrics.events_controller import EventsController

    EventsController("org", app).track_events("u1", [{"event_name": "level_up", "event_data": event_data}])


def test_a_repeat_event_with_known_keys_skips_postgres_but_still_reaches_clickhouse(schema_store):
    _track(level=1)
    reads, writes = schema_store.reads, schema_store.creates + schema_store.updates
    _track(level=2)
    assert (schema_store.reads, schema_store.creates + schema_store.updates) == (reads, writes)
    assert len(schema_store.pushed) == 2


def test_a_new_property_goes_back_to_postgres_and_is_added_to_the_schema(schema_store):
    _track(level=1)
    _track(level=2, coins=5)
    assert schema_store.reads == 2 and schema_store.updates == 1
    assert set(schema_store.rows[("app", "level_up")].event_schema["properties"]) == {"level", "coins"}


def test_an_existing_schema_that_gained_nothing_is_not_rewritten(schema_store, monkeypatch):
    from nova_manager.components.metrics import events_controller as ec

    _track(level=1)
    monkeypatch.setattr(ec, "_known_schema_keys", {})  # another worker process, cold cache
    _track(level=2)
    assert schema_store.reads == 2 and schema_store.updates == 0


def test_the_cache_expires_so_a_schema_row_removed_elsewhere_is_recreated(schema_store, monkeypatch):
    from nova_manager.components.metrics import events_controller as ec

    now = [1000.0]
    monkeypatch.setattr(ec.time, "monotonic", lambda: now[0])
    _track(level=1)
    now[0] += ec.SCHEMA_CACHE_TTL_S + 1
    _track(level=1)
    assert schema_store.reads == 2


def test_another_app_does_not_reuse_this_apps_cached_schema(schema_store):
    _track(app="app-a", level=1)
    _track(app="app-b", level=1)
    assert schema_store.reads == 2 and schema_store.creates == 2

