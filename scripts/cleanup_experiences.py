#!/usr/bin/env python3
"""
Wipe all experiences, feature flags, and their dependent data from Nova.

Deletes in FK-safe order within a single transaction.
Prompts for confirmation unless --yes is passed.

Usage:
  python -m scripts.cleanup_experiences
  python -m scripts.cleanup_experiences --yes          # skip prompt
  python -m scripts.cleanup_experiences --dry-run      # preview only
"""

import argparse
import sys

from sqlalchemy import text

from nova_manager.database.session import SessionLocal

# Deletion order matters — children before parents to respect FK constraints.
TABLES = [
    "user_experience",
    "personalisation_segment_rules",
    "personalisation_metrics",
    "personalisation_experience_variants",
    "personalisations",
    "experience_feature_variants",
    "experience_variants",
    "experience_features",
    "experience_metrics",
    "recommendations",
    "experiences",
    "feature_flags",
]


def get_counts(session) -> dict[str, int]:
    counts = {}
    for table in TABLES:
        result = session.execute(text(f"SELECT count(*) FROM {table}"))
        counts[table] = result.scalar()
    return counts


def run_cleanup(*, dry_run: bool = False, skip_confirm: bool = False):
    session = SessionLocal()

    try:
        print("\n--- Current record counts ---")
        counts = get_counts(session)
        total = 0
        for table, count in counts.items():
            total += count
            print(f"  {table:45s} {count:>6}")
        print(f"  {'TOTAL':45s} {total:>6}")

        if total == 0:
            print("\nNothing to clean up — all tables are already empty.")
            return

        if dry_run:
            print("\n[dry-run] No changes made.")
            return

        if not skip_confirm:
            answer = input(f"\nDelete all {total} records? [y/N] ").strip().lower()
            if answer != "y":
                print("Aborted.")
                return

        print("\nDeleting...")
        for table in TABLES:
            if counts[table] == 0:
                continue
            session.execute(text(f"DELETE FROM {table}"))
            print(f"  ✓ {table} — {counts[table]} deleted")

        session.commit()
        print("\nDone. All experiences and feature flags wiped.")

    except Exception as e:
        session.rollback()
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(
        description="Wipe all experiences, feature flags, and dependent data from Nova."
    )
    parser.add_argument(
        "--yes", "-y", action="store_true", help="Skip confirmation prompt"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview counts without deleting"
    )
    args = parser.parse_args()
    run_cleanup(dry_run=args.dry_run, skip_confirm=args.yes)


if __name__ == "__main__":
    main()
