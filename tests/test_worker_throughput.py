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
