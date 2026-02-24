#!/usr/bin/env python
"""
Idempotent script to create ClickHouse databases and tables for all existing apps.
Usage:
  poetry run python scripts/bootstrap_clickhouse.py
"""

import sys
import logging

from nova_manager.database.session import SessionLocal
from nova_manager.components.auth.models import App as AuthApp
from nova_manager.components.metrics.events_controller import EventsController

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    db = SessionLocal()
    try:
        # Find all (organisation_id, app_id) combinations from Apps table
        apps = db.query(AuthApp.organisation_id, AuthApp.pid).distinct().all()

        if not apps:
            logger.info("No apps found. Exiting.")
            return

        for organisation_id, app_id in apps:
            str_org = str(organisation_id)
            str_app = str(app_id)
            logger.info(f"Bootstrapping ClickHouse for org={str_org}, app={str_app}")

            controller = EventsController(str_org, str_app)

            # Create database (one per org/app)
            controller.create_database()

            # Create the 4 unified tables
            controller.create_raw_events_table()
            controller.create_event_props_table()
            controller.create_user_profile_table()
            controller.create_user_experience_table()

            logger.info(f"Done: org={str_org}, app={str_app}")

    finally:
        db.close()

    logger.info("ClickHouse bootstrap complete.")


if __name__ == "__main__":
    sys.exit(main())
