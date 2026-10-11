from typing import Callable, Optional

import redis
from rq import Queue
from rq.job import Job


from nova_manager.core.config import REDIS_URL, RQ_QUEUE_NAME


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
        job = self.default_queue.enqueue(func, *args, **kwargs)
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
