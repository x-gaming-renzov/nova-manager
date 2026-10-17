"""The production worker scales with its queue: up at once under load, down slowly when quiet,
always between 1 and 6, and the Cloud Run update can only ever change the instance count."""

import sys
from datetime import datetime, timedelta, timezone

import pytest

from nova_manager.queues import autoscaler as a


def test_a_backlog_scales_up_at_once_to_clear_it_in_about_ten_minutes():
    d = a.decide(queue_len=20_000, oldest_age_s=900, current=1, quiet_runs=0)
    assert d.workers == 6  # ceil(20000 / 4500) + 1 = 6


def test_never_more_than_six_workers_however_big_the_backlog():
    assert a.decide(queue_len=150_000, oldest_age_s=12_000, current=6, quiet_runs=0).workers == 6


def test_jobs_waiting_over_two_minutes_count_as_busy_even_in_a_short_queue():
    d = a.decide(queue_len=200, oldest_age_s=180, current=1, quiet_runs=0)
    assert d.workers >= 1 and d.reason.startswith("busy")


def test_busy_never_scales_down():
    assert a.decide(queue_len=1_500, oldest_age_s=10, current=5, quiet_runs=0).workers == 5


@pytest.mark.parametrize("runs_so_far", [0, 1, 2, 3])
def test_a_quiet_minute_alone_does_not_scale_down(runs_so_far):
    d = a.decide(queue_len=0, oldest_age_s=0, current=4, quiet_runs=runs_so_far)
    assert d.workers == 4
    assert d.quiet_runs == runs_so_far + 1


def test_five_quiet_minutes_remove_exactly_one_worker_and_restart_the_count():
    d = a.decide(queue_len=0, oldest_age_s=0, current=4, quiet_runs=4)
    assert (d.workers, d.quiet_runs) == (3, 0)


def test_never_fewer_than_one_worker():
    assert a.decide(queue_len=0, oldest_age_s=0, current=1, quiet_runs=10).workers == 1


def test_load_returning_resets_the_quiet_count():
    assert a.decide(queue_len=5_000, oldest_age_s=300, current=3, quiet_runs=4).quiet_runs == 0


class _FakeRedis:
    def __init__(self, queue, enqueued_at):
        self.queue, self.enqueued_at = queue, enqueued_at

    def llen(self, key):
        return len(self.queue)

    def lindex(self, key, i):
        return self.queue[i].encode() if self.queue else None

    def hget(self, key, field):
        return self.enqueued_at.encode() if self.enqueued_at else None


def test_queue_stats_reports_how_long_the_oldest_job_has_waited():
    enq = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()
    length, age = a.queue_stats(_FakeRedis(["j1", "j2"], enq), "default")
    assert length == 2 and 170 < age < 200


def test_an_empty_queue_has_no_waiting_time():
    assert a.queue_stats(_FakeRedis([], None), "default") == (0, 0.0)


class _FakeHttp:
    def __init__(self, service):
        self.service, self.patched = service, None

    def get(self, url, headers=None):
        body = {"access_token": "t"} if "metadata" in url else self.service
        return type("R", (), {"json": lambda s: body, "raise_for_status": lambda s: None})()

    def patch(self, url, params=None, json=None, headers=None):
        self.patched = (params, json)
        return type("R", (), {"raise_for_status": lambda s: None})()


def test_scaling_sends_the_whole_service_back_with_only_the_minimum_changed():
    service = {"name": "svc", "etag": "e1", "template": {"containers": [{"image": "img"}]},
               "scaling": {"minInstanceCount": 1, "maxInstanceCount": 6}}
    http = _FakeHttp(service)
    a.CloudRunScaler("projects/p/locations/r/services/svc", http=http).set_min(4)
    params, body = http.patched
    assert params == {"updateMask": "scaling.minInstanceCount"}
    assert body["template"] == service["template"] and body["etag"] == "e1"
    assert body["scaling"] == {"minInstanceCount": 4, "maxInstanceCount": 6}


@pytest.mark.skipif(sys.platform == "win32", reason="rq cannot be imported without fork()")
def test_jobs_are_enqueued_with_retries(monkeypatch):
    from nova_manager.queues import controller

    seen = {}

    class FakeQueue:
        def __init__(self, *a, **k):
            pass

        def enqueue(self, func, *args, **kwargs):
            seen.update(kwargs)
            return type("J", (), {"id": "j"})()

    monkeypatch.setattr(controller.redis, "from_url", lambda url: object())
    monkeypatch.setattr(controller, "Queue", FakeQueue)
    monkeypatch.setattr(controller.QueueController, "_instance", None)
    monkeypatch.setattr(controller.QueueController, "_initialized", False)
    controller.QueueController().add_task(print, "x")
    assert seen["retry"].max == 3
