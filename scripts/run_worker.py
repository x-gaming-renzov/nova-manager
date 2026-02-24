#!/usr/bin/env python
"""
RQ Worker script for Nova Manager
Run this script to process background tasks from the Redis queue
"""

import sys
import os
import platform
import signal
import argparse
from rq import Worker, SimpleWorker, Queue
from redis import from_url
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler


# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from nova_manager.core.config import REDIS_URL
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


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Run RQ worker for Nova Manager")
    parser.add_argument(
        "--burst",
        action="store_true",
        help="Run in burst mode (quit after processing all jobs)",
    )
    parser.add_argument(
        "--queue", default="default", help='Queue name to process (default: "default")'
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

        # Import worker dependencies here to make sure they're loaded
        # These imports ensure the worker has access to all necessary code

        logger.info("Required modules loaded successfully")

        # Create queue with explicit connection
        queue = Queue(args.queue, connection=conn)

        # Use SimpleWorker on macOS to avoid fork() crash with ObjC runtime
        # (ClickHouse/psycopg2 C extensions crash when forked on macOS)
        # In production (Linux), use the default Worker which forks for isolation.
        if platform.system() == "Darwin":
            logger.info("macOS detected — using SimpleWorker (no fork)")
            worker = SimpleWorker([queue], connection=conn)
        else:
            worker = Worker([queue], connection=conn)

        logger.info(f"Worker initialized, processing jobs from {args.queue} queue...")
        worker.work(burst=args.burst)

    except Exception as e:
        logger.error(f"Error starting worker: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
