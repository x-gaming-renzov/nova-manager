#!/usr/bin/env python
"""
RQ Worker script for Nova Manager
Run this script to process background tasks from the Redis queue
"""

import sys
import os
import signal
import argparse
from rq import SimpleWorker, Queue
from rq.worker_pool import WorkerPool
from redis import from_url
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler


# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from nova_manager.core.config import REDIS_URL, RQ_QUEUE_NAME, WORKER_PROCESSES
from nova_manager.core.log import logger, configure_logging


class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Worker healthy")

    def log_message(self, format, *args):
        # Suppress HTTP logs to keep worker logs clean
        return


def start_health_server(port=8080):
    """Start a simple HTTP server for Cloud Run health checks"""
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    logger.info(f"Health check server started on port {port}")


# Handle graceful shutdown on SIGTERM
def handle_sigterm(signum, frame):
    logger.info("Received SIGTERM signal. Shutting down worker gracefully...")
    # Worker will finish current job and exit
    sys.exit(0)


def build_worker(queue: Queue, conn) -> SimpleWorker:
    """Run jobs in this process instead of forking one per job.

    The forking Worker re-imported the app and reopened Postgres/ClickHouse in every child,
    ~2s of overhead around ~0.15s jobs, which capped throughput below launch traffic and
    let the queue fall hours behind.
    """
    return SimpleWorker([queue], connection=conn)


def build_pool(queue_name: str, conn, processes: int) -> WorkerPool:
    """Several in-process workers, one per forked child; the pool restarts any that die
    and, on SIGTERM, lets each finish its current job before exiting."""
    return WorkerPool([queue_name], connection=conn, num_workers=processes, worker_class=SimpleWorker)


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Run RQ worker for Nova Manager")
    parser.add_argument(
        "--burst",
        action="store_true",
        help="Run in burst mode (quit after processing all jobs)",
    )
    parser.add_argument(
        "--queue",
        default=RQ_QUEUE_NAME,
        help="Queue name to process (default: this environment's queue)",
    )
    args = parser.parse_args()

    # Configure logging
    configure_logging()
    logger.info(f"Starting RQ worker on queue: {args.queue}")

    # Register signal handler for graceful shutdown
    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    try:
        port = int(os.environ.get("PORT", 8080))
        start_health_server(port)
        # Connect to Redis
        conn = from_url(REDIS_URL)
        logger.info(f"Connected to Redis at {REDIS_URL}")

        if WORKER_PROCESSES > 1:
            logger.info(f"Starting {WORKER_PROCESSES} worker processes on {args.queue}...")
            build_pool(args.queue, conn, WORKER_PROCESSES).start(burst=args.burst)
            sys.exit(0)

        queue = Queue(args.queue, connection=conn)
        worker = build_worker(queue, conn)

        logger.info(f"Worker initialized, processing jobs from {args.queue} queue...")
        # The scheduler runs the retry intervals. work() returns on SIGTERM (after finishing the
        # current job) or when it gives up on Redis; either way exit, so Cloud Run replaces the
        # instance instead of keeping a container whose health check answers but takes no jobs.
        worker.work(burst=args.burst, with_scheduler=True)
        sys.exit(0 if worker._stop_requested else 1)

    except Exception as e:
        logger.error(f"Error starting worker: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
