"""Queue-driven instance count for the production worker (Cloud Run scales on CPU/requests,
and a worker waiting on ClickHouse looks idle to it, so the backlog never triggers a scale-up).

Run once a minute: read the queue, decide, set the worker service's minimum instance count.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx

MIN_WORKERS = 1
MAX_WORKERS = 6
JOBS_PER_WORKER_PER_MIN = 450  # measured on e2-standard-2, 17 Oct 2026
DRAIN_TARGET_MIN = 10
BUSY_AGE_S = 120
BUSY_QUEUE = 1000
QUIET_AGE_S = 30
QUIET_RUNS_BEFORE_SCALE_DOWN = 5
STATE_KEY = "nova:autoscaler:quiet_runs"


@dataclass(frozen=True)
class Decision:
    workers: int
    quiet_runs: int
    reason: str


def decide(queue_len: int, oldest_age_s: float, current: int, quiet_runs: int) -> Decision:
    """Scale up at once under load; step down one worker only after sustained quiet."""
    needed = math.ceil(queue_len / (JOBS_PER_WORKER_PER_MIN * DRAIN_TARGET_MIN)) + 1
    needed = max(MIN_WORKERS, min(MAX_WORKERS, needed))
    if queue_len >= BUSY_QUEUE or oldest_age_s >= BUSY_AGE_S:
        workers = max(current, needed)
        return Decision(workers, 0, f"busy: {queue_len} queued, oldest {oldest_age_s:.0f}s")
    if oldest_age_s <= QUIET_AGE_S and needed < current:
        quiet_runs += 1
        if quiet_runs >= QUIET_RUNS_BEFORE_SCALE_DOWN:
            return Decision(current - 1, 0, f"quiet for {quiet_runs} runs: one worker fewer")
        return Decision(current, quiet_runs, f"quiet {quiet_runs}/{QUIET_RUNS_BEFORE_SCALE_DOWN}")
    return Decision(max(MIN_WORKERS, min(MAX_WORKERS, current)), 0, "steady")


def queue_stats(redis_conn, queue_name: str) -> tuple[int, float]:
    """Length of the queue and how long its oldest job has been waiting, in seconds."""
    length = redis_conn.llen(f"rq:queue:{queue_name}")
    head = redis_conn.lindex(f"rq:queue:{queue_name}", 0)
    if not head:
        return length, 0.0
    enqueued_at = redis_conn.hget(f"rq:job:{head.decode()}", "enqueued_at")
    if not enqueued_at:
        return length, 0.0
    stamp = datetime.fromisoformat(enqueued_at.decode().replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return length, max(0.0, (datetime.now(timezone.utc) - stamp).total_seconds())


METADATA_TOKEN_URL = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"


MIN_SCALE = "run.googleapis.com/minScale"
MAX_SCALE = "run.googleapis.com/maxScale"


class CloudRunScaler:
    """Reads and sets a service's minimum instance count through the service-level annotation,
    which changes no template, so no new revision.

    Uses the v1 (Knative) API, as gcloud does: v2 validates the stored template on every update
    and rejects this service's short VPC connector name, so even a scaling-only PATCH fails.
    """

    def __init__(self, service_path: str, http: Optional[httpx.Client] = None):
        _, project, _, region, _, name = service_path.split("/")
        self.url = f"https://{region}-run.googleapis.com/apis/serving.knative.dev/v1/namespaces/{project}/services/{name}"
        self.http = http or httpx.Client(timeout=30)

    def _headers(self) -> dict:
        token = self.http.get(METADATA_TOKEN_URL, headers={"Metadata-Flavor": "Google"}).json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    def _service(self) -> dict:
        resp = self.http.get(self.url, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    def current_min(self) -> int:
        return int(self._service()["metadata"].get("annotations", {}).get(MIN_SCALE) or 0)

    def set_min(self, count: int) -> None:
        # Replace the service exactly as read (resourceVersion guards a concurrent change), with
        # only the scaling annotations changed, so nothing else can be dropped.
        service = self._service()
        annotations = service["metadata"].setdefault("annotations", {})
        annotations[MIN_SCALE] = str(count)
        annotations[MAX_SCALE] = str(MAX_WORKERS)
        resp = self.http.put(self.url, json=service, headers=self._headers())
        if resp.status_code >= 400:
            # Google names the missing permission in the body; raise_for_status alone drops it.
            raise RuntimeError(f"setting minScale={count} failed: {resp.status_code} {resp.text[:500]}")
