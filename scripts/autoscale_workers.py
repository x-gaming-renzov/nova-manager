#!/usr/bin/env python
"""One autoscaling pass for the production worker; Cloud Scheduler runs it every minute."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from redis import from_url

from nova_manager.core.config import REDIS_URL, RQ_QUEUE_NAME
from nova_manager.core.log import configure_logging, logger
from nova_manager.queues.autoscaler import STATE_KEY, CloudRunScaler, decide, queue_stats


def main() -> None:
    configure_logging()
    service = os.environ["WORKER_SERVICE_PATH"]  # projects/<p>/locations/<r>/services/<name>
    conn = from_url(REDIS_URL)
    scaler = CloudRunScaler(service)

    queue_len, oldest_age = queue_stats(conn, RQ_QUEUE_NAME)
    current = scaler.current_min()
    decision = decide(queue_len, oldest_age, current, int(conn.get(STATE_KEY) or 0))
    conn.set(STATE_KEY, decision.quiet_runs)
    if decision.workers != current:
        scaler.set_min(decision.workers)
    logger.info(
        f"autoscaler: queue={queue_len} oldest={oldest_age:.0f}s workers {current} -> {decision.workers} ({decision.reason})"
    )


if __name__ == "__main__":
    main()
