"""Shared helpers for integration tests."""

import json
import sys
import uuid

import requests

RUN_ID = uuid.uuid4().hex[:8]

passed = 0
failed = 0
errors = []


def pp(data):
    print(json.dumps(data, indent=2, default=str))


def step(num, title):
    print(f"\n{'─' * 60}")
    print(f"  Step {num}: {title}")
    print(f"{'─' * 60}")


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        errors.append(f"{name}: {detail}")
        print(f"  FAIL  {name} — {detail}")
    return condition


def summary():
    print(f"\n{'=' * 60}")
    print(f"  Results: {passed} passed, {failed} failed")
    print(f"{'=' * 60}")
    if errors:
        print("\nFailures:")
        for e in errors:
            print(f"  - {e}")
    return failed == 0
