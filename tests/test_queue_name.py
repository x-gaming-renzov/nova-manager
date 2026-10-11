"""Each environment has its own job queue.

Staging and production share one Redis; on a shared queue name either environment's worker
could take the other's jobs.
"""

import pytest

from nova_manager.core.config import rq_queue_name


def test_production_keeps_the_original_queue_so_jobs_already_queued_are_not_stranded():
    assert rq_queue_name("production") == "default"


@pytest.mark.parametrize("env", ["staging", "local", "dev-2"])
def test_other_environments_get_a_queue_of_their_own(env):
    name = rq_queue_name(env)
    assert name != "default"
    assert name != rq_queue_name("production")


def test_two_non_production_environments_do_not_share_a_queue():
    assert rq_queue_name("staging") != rq_queue_name("local")


def test_the_api_enqueues_on_the_same_queue_the_worker_listens_to(monkeypatch):
    from nova_manager.core import config
    from nova_manager.queues import controller

    monkeypatch.setattr(controller.redis, "from_url", lambda url: object())
    created = {}

    class FakeQueue:
        def __init__(self, name="default", connection=None):
            created["name"] = name

    monkeypatch.setattr(controller, "Queue", FakeQueue)
    monkeypatch.setattr(controller.QueueController, "_instance", None)
    monkeypatch.setattr(controller.QueueController, "_initialized", False)
    controller.QueueController()
    assert created["name"] == config.RQ_QUEUE_NAME
