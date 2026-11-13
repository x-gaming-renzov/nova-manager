#!/usr/bin/env python
"""Send the daily "Nova status" email; Cloud Scheduler runs the nova-daily-status job at 09:00 IST.

Settings: STATUS_REPORT_RECIPIENTS (comma separated), BREVO_API_KEY, optional STATUS_REPORT_SENDER.
--dry-run prints the subject and writes the HTML to status_report.html instead of sending
(locally, set ACCESS_TOKEN=$(gcloud auth print-access-token)).
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import httpx

from nova_manager.core.log import configure_logging, logger
from nova_manager.service.status_report import (
    Gcp, build_report, fetch_senders, parse_recipients, pick_sender, render, send_email,
)


def main() -> None:
    configure_logging()
    now = datetime.now(timezone.utc)
    report = build_report(Gcp(now, token=os.environ.get("ACCESS_TOKEN")), now)
    subject, body = render(report)
    if "--dry-run" in sys.argv:
        with open("status_report.html", "w", encoding="utf-8") as out:
            out.write(body)
        print(subject)
        return

    recipients = parse_recipients(os.environ.get("STATUS_REPORT_RECIPIENTS", ""))
    api_key = os.environ.get("BREVO_API_KEY", "")
    if not recipients or not api_key:
        raise SystemExit("STATUS_REPORT_RECIPIENTS and BREVO_API_KEY must both be set")
    http = httpx.Client(timeout=30)
    sender = pick_sender(fetch_senders(http, api_key), os.environ.get("STATUS_REPORT_SENDER"))
    send_email(http, api_key, sender, recipients, subject, body)
    logger.info(f"status report sent to {len(recipients)} recipients: {subject}")


if __name__ == "__main__":
    main()
