from typing import Callable, Optional

import redis
from rq import Queue, Retry
from rq.job import Job


from nova_manager.core.config import REDIS_URL, RQ_QUEUE_NAME


JOB_RETRY = Retry(max=3, interval=[10, 30, 60])


class QueueController:
    _instance: Optional["QueueController"] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # Only initialize once
        if not self._initialized:
            self.redis_conn = redis.from_url(REDIS_URL)
            self.default_queue = Queue(RQ_QUEUE_NAME, connection=self.redis_conn)
            self._initialized = True

    def add_task(self, func: Callable, *args, **kwargs) -> str:
        """Add a task and return task ID"""
        # Retried after a ClickHouse/Redis blip or when a scaled-down worker abandons it, so a
        # restart no longer strands jobs in the failed registry.
        # rq logs a job's description when it starts and finishes; by default that is the call
        # with its arguments, which carry players' event payloads and profiles.
        job = self.default_queue.enqueue(
            func, *args, retry=JOB_RETRY, description=func.__qualname__, **kwargs
        )
        return job.id

    def get_task_status(self, job_id: str):
        """Get task status"""

        task = Job.fetch(job_id, connection=self.redis_conn)
        return {
            "id": task.id,
            "status": task.get_status(),
            "result": task.result,
            "created_at": task.created_at,
            "started_at": task.started_at,
            "ended_at": task.ended_at,
        }
