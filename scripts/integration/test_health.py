"""Step 0: Health check — verifies API is reachable."""

import sys
import requests
from scripts.integration.helpers import step, check

# Cloud Run can take up to 30s to cold-start
HEALTH_TIMEOUT = 30


def run(base: str, _state: dict):
    step(0, "Health Check")
    try:
        r = requests.get(f"{base}/health", timeout=HEALTH_TIMEOUT)
        check("GET /health returns 200", r.status_code == 200, f"got {r.status_code}")
        if r.status_code == 200:
            check("/health body has status=ok", r.json().get("status") == "ok", f"got {r.json()}")
    except (requests.ConnectionError, requests.Timeout) as e:
        check("API reachable", False, str(e))
        print("\nAPI is not reachable. Aborting.")
        sys.exit(1)
