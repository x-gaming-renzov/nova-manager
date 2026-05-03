#!/usr/bin/env python3
"""
Nova Manager - Post-Deployment Integration Test Runner

Runs all integration test modules in order. Each module tests a specific area
of the deployed stack. Uses a shared state dict to pass tokens between modules.

Usage:
  python scripts/smoke_test.py --base-url https://nova-manager-XXXXX.run.app
  python scripts/smoke_test.py  # defaults to http://localhost:8000
"""

import argparse
import sys

from scripts.integration import helpers
from scripts.integration.helpers import RUN_ID, summary
from scripts.integration import (
    test_health,
    test_auth,
    test_apps,
    test_sdk,
    test_crud,
    test_events,
    test_business_metrics,
    test_invitations,
    test_auth_guards,
)

# Ordered list — each module receives (base_url, state_dict)
MODULES = [
    test_health,        # 0: health check
    test_auth,          # 1-4: register, login, refresh, /me
    test_apps,          # 5-7: create app, list, switch, org users
    test_sdk,           # 8, 13: SDK credentials, create users
    test_crud,          # 9-12: feature flags, segments, experiences, personalisations
    test_events,        # 14-17: track events, worker, metrics compute, schema
    test_business_metrics,  # 20-26: business data, operational & formula metrics
    test_invitations,   # 18: send invitation, list, validate (email)
    test_auth_guards,   # 19: unauthorized access checks
]


def main():
    parser = argparse.ArgumentParser(description="Nova Manager integration tests")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL of the deployed API (default: http://localhost:8000)",
    )
    args = parser.parse_args()

    base = args.base_url.rstrip("/")

    print(f"Nova Manager Integration Tests (run: {RUN_ID})")
    print(f"Target: {base}")
    print(f"{'=' * 60}")

    state = {}

    for module in MODULES:
        module.run(base, state)

    ok = summary()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
