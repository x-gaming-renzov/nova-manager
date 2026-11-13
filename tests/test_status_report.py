"""Daily "Nova status" email: levels, the rendered message, Brevo delivery and best-effort collection."""

from datetime import datetime, timezone

import pytest

from nova_manager.service import status_report as sr
from nova_manager.service.status_report import Level, Reading, Report, Section

NOW = datetime(2026, 11, 14, 3, 30, tzinfo=timezone.utc)
RECIPIENTS = ["ops1@example.com", "ops2@example.com"]


# ── Levels ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("value,expected", [
    (None, Level.UNKNOWN), (0.0, Level.OK), (69.9, Level.OK), (70.0, Level.WARNING),
    (84.9, Level.WARNING), (85.0, Level.CRITICAL), (100.0, Level.CRITICAL),
])
def test_a_reading_is_rated_against_its_warning_and_critical_limits(value, expected):
    assert Reading("CPU", value, "%", warn=70, crit=85).level == expected


@pytest.mark.parametrize("value,expected", [
    (100.0, Level.OK), (99.9, Level.OK), (99.89, Level.WARNING), (99.0, Level.WARNING),
    (98.99, Level.CRITICAL), (None, Level.UNKNOWN),
])
def test_uptime_is_worse_when_lower(value, expected):
    assert Reading("Uptime", value, "%", warn=99.9, crit=99.0, lower_is_worse=True).level == expected


def test_a_reading_without_limits_is_informational_and_never_raises_the_level():
    assert Reading("Requests", 342411, "").level == Level.OK


def test_a_missing_value_is_unknown_not_ok():
    """Null means unknown: a source we could not read must not look healthy."""
    assert Reading("Connections", None, "", warn=100, crit=120).level == Level.UNKNOWN


def test_the_overall_level_is_the_worst_reading_in_any_section():
    report = Report(NOW, sections=[
        Section("A", "plan", [Reading("x", 10, "%", warn=70, crit=85)]),
        Section("B", "plan", [Reading("y", None, "%", warn=70, crit=85), Reading("z", 75, "%", warn=70, crit=85)]),
    ])
    assert report.overall == Level.WARNING


def test_unknown_outranks_ok_but_not_warning():
    ok_and_unknown = Report(NOW, sections=[Section("A", "", [Reading("x", 1, "", warn=5, crit=9), Reading("y", None, "", warn=5, crit=9)])])
    assert ok_and_unknown.overall == Level.UNKNOWN


# ── Rendering ────────────────────────────────────────────────────────


def _report():
    return Report(NOW, sections=[
        Section("Prod API (nova-manager)", "1 vCPU / 512 MiB, 0-10 instances, revision nova-manager-00036-fxv", [
            Reading("Requests (24 h)", 342411, ""),
            Reading("5xx rate", 4.36, "%", warn=2, crit=5),
            Reading("CPU p95", None, "%", warn=70, crit=85),
        ]),
        Section("Cloud SQL nova-db", "db-g1-small, 31 GB SSD, automatic backups OFF", [
            Reading("Connections peak", 51, " of 150", warn=100, crit=120),
        ], notes=["Automatic backups are disabled."]),
    ], alerts=[{"opened": "2026-11-13 13:18", "closed": "2026-11-13 14:28", "name": "[URGENT] Nova ClickHouse down"}])


def test_subject_names_the_overall_status_date_and_counts():
    subject, _ = sr.render(_report())
    assert subject == "Nova status: WARNING | 2026-11-14 | 1 warning, 0 critical, 1 no data"


def test_body_lists_every_section_with_its_plan_values_and_levels():
    _, html = sr.render(_report())
    for text in ("Prod API (nova-manager)", "1 vCPU / 512 MiB, 0-10 instances, revision nova-manager-00036-fxv",
                 "Cloud SQL nova-db", "db-g1-small, 31 GB SSD, automatic backups OFF",
                 "342,411", "4.36%", "51 of 150", "WARNING", "Automatic backups are disabled."):
        assert text in html, text


def test_a_value_that_could_not_be_read_says_no_data_and_never_zero():
    _, html = sr.render(_report())
    row = html[html.index("CPU p95"):html.index("CPU p95") + 300]
    assert "no data" in row and "0%" not in row


def test_body_lists_the_alerts_that_fired_in_the_window():
    _, html = sr.render(_report())
    assert "[URGENT] Nova ClickHouse down" in html and "2026-11-13 13:18" in html


def test_a_quiet_day_says_no_alerts_fired():
    _, html = sr.render(Report(NOW, sections=[], alerts=[]))
    assert "No alerts fired" in html


def test_section_and_alert_text_is_html_escaped():
    report = Report(NOW, sections=[Section("<script>x</script>", "a & b", [])],
                    alerts=[{"opened": "t", "closed": "t", "name": "<b>bad</b>"}])
    _, html = sr.render(report)
    assert "<script>" not in html and "&lt;script&gt;" in html and "&lt;b&gt;bad&lt;/b&gt;" in html


# ── Sender and delivery ──────────────────────────────────────────────


def test_the_configured_sender_wins():
    senders = [{"email": "other@example.com", "name": "o", "active": True}]
    assert sr.pick_sender(senders, "ops@example.com") == {"email": "ops@example.com", "name": "Nova status"}


def test_without_a_configured_sender_the_first_active_verified_sender_is_used():
    senders = [{"email": "off@example.com", "name": "x", "active": False},
               {"email": "on@example.com", "name": "xg", "active": True}]
    assert sr.pick_sender(senders, None) == {"email": "on@example.com", "name": "Nova status"}


def test_no_active_sender_is_a_loud_error():
    with pytest.raises(RuntimeError, match="no active Brevo sender"):
        sr.pick_sender([{"email": "off@example.com", "active": False}], None)


class FakeHttp:
    def __init__(self, status=201, body=None, senders=None):
        self.status, self.body, self.senders, self.posts = status, body or {"messageId": "m1"}, senders, []

    def post(self, url, json=None, headers=None):
        self.posts.append({"url": url, "json": json, "headers": headers})
        return _Resp(self.status, self.body)

    def get(self, url, headers=None, params=None):
        return _Resp(200, {"senders": self.senders or []})


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, str(body)

    def json(self):
        return self._body


def test_the_email_goes_to_every_recipient_through_brevo_as_html():
    http = FakeHttp()
    sr.send_email(http, "key-1", {"email": "s@example.com", "name": "Nova status"}, RECIPIENTS, "subj", "<p>hi</p>")
    [post] = http.posts
    assert post["url"] == "https://api.brevo.com/v3/smtp/email"
    assert post["headers"]["api-key"] == "key-1"
    assert post["json"] == {
        "sender": {"email": "s@example.com", "name": "Nova status"},
        "to": [{"email": "ops1@example.com"}, {"email": "ops2@example.com"}],
        "subject": "subj", "htmlContent": "<p>hi</p>",
    }


def test_a_rejected_email_raises_so_the_job_run_fails():
    with pytest.raises(RuntimeError, match="Brevo rejected the status email: HTTP 401"):
        sr.send_email(FakeHttp(status=401, body={"message": "unrecognised IP"}), "k",
                      {"email": "s@example.com", "name": "n"}, RECIPIENTS, "s", "h")


@pytest.mark.parametrize("raw,expected", [
    ("a@x.com,b@y.com", ["a@x.com", "b@y.com"]), (" a@x.com , ,b@y.com ", ["a@x.com", "b@y.com"]), ("", []),
])
def test_recipients_are_read_from_a_comma_separated_setting(raw, expected):
    assert sr.parse_recipients(raw) == expected


# ── Collection is best effort per source ─────────────────────────────


class FakeGcp:
    """Answers metric queries from a table keyed by metric type; anything listed in `broken` raises."""

    def __init__(self, metrics=None, broken=(), resources=None):
        self.metrics, self.broken, self.resources = metrics or {}, set(broken), resources or {}

    def series(self, metric_filter, aligner, reducer=None, group_by=(), period_s=86400, hours=24):
        for metric, values in self.metrics.items():
            if f'metric.type="{metric}"' in metric_filter:
                if metric in self.broken:
                    raise RuntimeError(f"Monitoring API failed for {metric}")
                return values(metric_filter, group_by) if callable(values) else values
        if any(f'metric.type="{m}"' in metric_filter for m in self.broken):
            raise RuntimeError("Monitoring API failed")
        return {}

    def get(self, url, params=None):
        for fragment, body in self.resources.items():
            if fragment in url:
                if isinstance(body, Exception):
                    raise body
                return body
        raise RuntimeError(f"unexpected url {url}")


SQL_INSTANCE = {"settings": {"tier": "db-g1-small", "dataDiskSizeGb": "31",
                             "backupConfiguration": {"enabled": False},
                             "databaseFlags": [{"name": "max_connections", "value": "150"}]},
                "state": "RUNNABLE"}


def test_a_source_that_fails_leaves_its_readings_unknown_and_the_rest_of_the_report_intact():
    gcp = FakeGcp(
        metrics={
            "cloudsql.googleapis.com/database/cpu/utilization": {(): [0.10, 0.40]},
            "cloudsql.googleapis.com/database/memory/utilization": {(): [0.62]},
        },
        broken={"cloudsql.googleapis.com/database/postgresql/num_backends"},
        resources={"sqladmin": SQL_INSTANCE},
    )
    section = sr.collect_cloud_sql(gcp)
    by_name = {r.name: r for r in section.readings}
    assert by_name["CPU peak"].value == pytest.approx(40.0)
    assert by_name["Memory peak"].value == pytest.approx(62.0)
    assert by_name["Connections peak"].value is None and by_name["Connections peak"].level == Level.UNKNOWN
    assert "db-g1-small" in section.plan and "backups OFF" in section.plan
    assert any("Automatic backups are disabled" in n for n in section.notes)


def test_connection_limits_scale_with_the_configured_max_connections():
    gcp = FakeGcp(metrics={"cloudsql.googleapis.com/database/postgresql/num_backends": {(): [100.0]}},
                  resources={"sqladmin": SQL_INSTANCE})
    conns = {r.name: r for r in sr.collect_cloud_sql(gcp).readings}["Connections peak"]
    assert (conns.value, conns.unit, conns.level) == (100.0, " of 150", Level.WARNING)


class PagedLogs(FakeGcp):
    """The Logging API may return an empty page that still carries a nextPageToken when matches are sparse."""

    def __init__(self, pages):
        super().__init__()
        self.pages, self.now = list(pages), NOW

    def post(self, url, body):
        return self.pages.pop(0)


def test_out_of_memory_kills_are_counted_across_every_page_of_log_results():
    gcp = PagedLogs([{"nextPageToken": "a"}, {"entries": [{}, {}], "nextPageToken": "b"}, {"entries": [{}]}])
    assert sr._count_oom_kills(gcp, "6898244829417515989") == 3.0


RUN_SERVICE = {"spec": {"template": {"metadata": {"annotations": {"autoscaling.knative.dev/maxScale": "10"}},
                                     "spec": {"containers": [{"resources": {"limits": {"cpu": "1", "memory": "512Mi"}}}]}}},
               "status": {"latestReadyRevisionName": "nova-manager-00036-fxv", "conditions": [{"type": "Ready", "status": "True"}]}}


def test_peak_instances_are_measured_per_revision_not_summed_across_a_deploy_overlap():
    def instances(metric_filter, group_by):
        # instance_count is split into active and idle; adding both states' maxima overcounts.
        if "resource.label.revision_name" in group_by and 'metric.label.state="active"' in metric_filter:
            return {("nova-manager-00035-sml",): [6.0, 4.0], ("nova-manager-00036-fxv",): [8.0]}
        return {(): [14.0]}  # old + new revision summed while traffic moved over

    gcp = FakeGcp(metrics={"run.googleapis.com/container/instance_count": instances},
                  resources={"run.googleapis.com": RUN_SERVICE})
    peak = {r.name: r for r in sr.collect_cloud_run(gcp, "Prod API", "nova-manager", False).readings}["Peak instances"]
    assert (peak.value, peak.unit, peak.level) == (8.0, " of 10", Level.WARNING)


def test_build_report_still_produces_a_report_when_a_whole_collector_crashes(monkeypatch):
    def works(gcp):
        return Section("Works", "p", [Reading("x", 1, "")])

    def crashes(gcp):
        raise RuntimeError("compute API down")

    monkeypatch.setattr(sr, "COLLECTORS", [works, crashes])
    monkeypatch.setattr(sr, "collect_alerts", lambda gcp, now: [])
    report = sr.build_report(FakeGcp(), NOW)
    assert [s.title for s in report.sections][0] == "Works"
    failed = report.sections[1]
    assert failed.readings[0].value is None and "compute API down" in failed.notes[0]
    assert report.overall == Level.UNKNOWN
