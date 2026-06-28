#!/usr/bin/env python3
"""
Empty all Nova data on a *deployed* instance over HTTP — no DB shell needed.

Calls POST {url}/api/v1/admin/cleanup with the shared admin key, which TRUNCATEs
every Postgres table and every per-app ClickHouse analytics table (schema kept).

The key is read from --key or the NOVA_ADMIN_KEY env var. Always does a --dry-run
preview first; the real wipe needs confirmation (or --yes).

Usage:
  NOVA_ADMIN_KEY=secret python -m scripts.cleanup_nova_via_api --url https://nova.example.com
  python -m scripts.cleanup_nova_via_api --url http://localhost:8000 --dry-run
  python -m scripts.cleanup_nova_via_api --url https://nova.example.com --key secret --yes
"""

import argparse
import os
import sys

import httpx

ADMIN_KEY_HEADER = "X-Nova-Admin-Key"


def _post(url: str, key: str, dry_run: bool) -> dict:
    endpoint = url.rstrip("/") + "/api/v1/admin/cleanup"
    resp = httpx.post(
        endpoint,
        headers={ADMIN_KEY_HEADER: key},
        json={"dry_run": dry_run},
        timeout=120.0,
    )
    if resp.status_code == 401:
        print("ERROR: admin key rejected (401). Check NOVA_ADMIN_KEY.", file=sys.stderr)
        sys.exit(1)
    resp.raise_for_status()
    return resp.json()


def _print_summary(result: dict) -> None:
    pg, ch = result["postgres"], result["clickhouse"]
    print("\n--- Postgres (rows) ---")
    for table, count in pg.items():
        print(f"  {table:45s} {count:>8}")
    print(f"  {'TOTAL':45s} {result['postgres_total']:>8}")
    print("\n--- ClickHouse (rows) ---")
    if ch:
        for table, count in ch.items():
            print(f"  {table:45s} {count:>8}")
    else:
        print("  (no per-app analytics tables found)")
    print(f"  {'TOTAL':45s} {result['clickhouse_total']:>8}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Empty all Nova data via the admin API.")
    parser.add_argument("--url", required=True, help="Base URL of the Nova instance")
    parser.add_argument("--key", default=os.getenv("NOVA_ADMIN_KEY", ""),
                        help="Admin key (defaults to NOVA_ADMIN_KEY env var)")
    parser.add_argument("--dry-run", action="store_true", help="Preview counts only")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")
    args = parser.parse_args()

    if not args.key:
        print("ERROR: no admin key. Pass --key or set NOVA_ADMIN_KEY.", file=sys.stderr)
        sys.exit(2)

    # Always preview first.
    preview = _post(args.url, args.key, dry_run=True)
    _print_summary(preview)
    total = preview["postgres_total"] + preview["clickhouse_total"]

    if args.dry_run:
        print("\n[dry-run] No changes made.")
        return
    if total == 0:
        print("\nNothing to clean up — everything is already empty.")
        return
    if not args.yes:
        answer = input(f"\nEmpty ALL Nova data at {args.url} ({total} rows)? [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted.")
            return

    result = _post(args.url, args.key, dry_run=False)
    print("\nDone. Nova data emptied (tables preserved).")
    print(f"  Postgres rows removed:   {result['postgres_total']}")
    print(f"  ClickHouse rows removed: {result['clickhouse_total']}")


if __name__ == "__main__":
    main()
