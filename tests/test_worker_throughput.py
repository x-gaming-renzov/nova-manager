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
