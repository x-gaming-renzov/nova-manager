"""Daily Nova status email: reads the health of every Nova component and sends one summary.

Runs as the `nova-daily-status` Cloud Run job (scripts/daily_status_report.py), once a day.
A reading that could not be fetched is shown as "no data" (UNKNOWN), never as zero: a source
we could not read must not look healthy.
"""

import html
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import IntEnum
from typing import Callable, Optional

import httpx

from nova_manager.core.log import logger

PROJECT = "xgaminn"
REGION = "us-central1"
METADATA_TOKEN_URL = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
MONITORING = f"https://monitoring.googleapis.com/v3/projects/{PROJECT}"
BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"
BREVO_SENDERS_URL = "https://api.brevo.com/v3/senders"
IST = timezone(timedelta(hours=5, minutes=30))


class Level(IntEnum):
    OK = 0
    UNKNOWN = 1
    WARNING = 2
    CRITICAL = 3


LABELS = {Level.OK: "OK", Level.UNKNOWN: "NO DATA", Level.WARNING: "WARNING", Level.CRITICAL: "CRITICAL"}
COLOURS = {Level.OK: "#1e7e34", Level.UNKNOWN: "#6c757d", Level.WARNING: "#b8860b", Level.CRITICAL: "#c82333"}


@dataclass
class Reading:
    name: str
    value: Optional[float]
    unit: str = ""
    warn: Optional[float] = None
    crit: Optional[float] = None
    lower_is_worse: bool = False
    text: Optional[str] = None  # shown instead of the number, e.g. "yes"

    @property
    def level(self) -> Level:
        if self.value is None:
            return Level.UNKNOWN
        worse = (lambda v, limit: v < limit) if self.lower_is_worse else (lambda v, limit: v >= limit)
        if self.crit is not None and worse(self.value, self.crit):
            return Level.CRITICAL
        if self.warn is not None and worse(self.value, self.warn):
            return Level.WARNING
        return Level.OK

    def display(self) -> str:
        if self.value is None:
            return "no data"
        if self.text is not None:
            return self.text
        number = f"{int(self.value):,}" if float(self.value).is_integer() else f"{self.value:,.2f}"
        return f"{number}{self.unit}"


@dataclass
class Section:
    title: str
    plan: str
    readings: list[Reading]
    notes: list[str] = field(default_factory=list)


@dataclass
class Report:
    generated_at: datetime
    sections: list[Section]
    alerts: list[dict] = field(default_factory=list)
    window_hours: int = 24

    def _levels(self) -> list[Level]:
        return [r.level for s in self.sections for r in s.readings]

    @property
    def overall(self) -> Level:
        return max(self._levels(), default=Level.OK)

    def count(self, level: Level) -> int:
        return self._levels().count(level)


# ── Rendering ────────────────────────────────────────────────────────


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 or word == "critical" else "s")


def _badge(level: Level) -> str:
    return (f'<span style="color:#fff;background:{COLOURS[level]};padding:1px 6px;border-radius:3px;'
            f'font-size:12px">{LABELS[level]}</span>')


def _limits(r: Reading) -> str:
    sign = "&lt;" if r.lower_is_worse else "&ge;"
    parts = [f"warn {sign} {r.warn:.4g}" if r.warn is not None else "", f"critical {sign} {r.crit:.4g}" if r.crit is not None else ""]
    return ", ".join(p for p in parts if p)


def render(report: Report) -> tuple[str, str]:
    """Subject and HTML body of the daily status email."""
    e = html.escape
    counts = (f"{_plural(report.count(Level.WARNING), 'warning')}, {_plural(report.count(Level.CRITICAL), 'critical')}, "
              f"{report.count(Level.UNKNOWN)} no data")
    subject = f"Nova status: {LABELS[report.overall]} | {report.generated_at:%Y-%m-%d} | {counts}"
    parts = [
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#222;max-width:820px">',
        f'<h2 style="margin:0 0 4px">Nova status: {_badge(report.overall)}</h2>',
        f'<p style="margin:0 0 12px;color:#555">Last {report.window_hours} h, up to '
        f"{report.generated_at:%Y-%m-%d %H:%M} UTC ({report.generated_at.astimezone(IST):%H:%M} IST). {counts}.</p>",
    ]
    for section in report.sections:
        parts.append(f'<h3 style="margin:16px 0 2px">{e(section.title)}</h3>')
        parts.append(f'<p style="margin:0 0 6px;color:#555">Plan: {e(section.plan)}</p>')
        parts.append('<table style="border-collapse:collapse;width:100%">')
        for r in section.readings:
            parts.append(
                '<tr style="border-bottom:1px solid #eee">'
                f'<td style="padding:3px 6px">{e(r.name)}</td>'
                f'<td style="padding:3px 6px;text-align:right"><b>{e(r.display())}</b></td>'
                f'<td style="padding:3px 6px">{_badge(r.level)}</td>'
                f'<td style="padding:3px 6px;color:#888;font-size:12px">{_limits(r)}</td></tr>'
            )
        parts.append("</table>")
        if section.notes:
            parts.append('<ul style="margin:4px 0;color:#7a4b00">' + "".join(f"<li>{e(n)}</li>" for n in section.notes) + "</ul>")
    parts.append(f'<h3 style="margin:16px 0 2px">Alerts fired in the last {report.window_hours} h</h3>')
    if report.alerts:
        parts.append("<ul>" + "".join(
            f"<li>{e(a['opened'])} to {e(a['closed'])}: {e(a['name'])}</li>" for a in report.alerts) + "</ul>")
    else:
        parts.append("<p>No alerts fired.</p>")
    parts.append(
        '<p style="margin-top:16px;color:#888;font-size:12px">Informational daily summary from the nova-daily-status '
        "Cloud Run job (09:00 IST). Urgent problems are emailed separately the moment an alert fires. "
        '"no data" means the value could not be read, which is not the same as zero.</p></div>'
    )
    return subject, "".join(parts)


# ── Delivery (Brevo) ─────────────────────────────────────────────────


def parse_recipients(raw: str) -> list[str]:
    return [address.strip() for address in raw.split(",") if address.strip()]


def pick_sender(senders: list[dict], configured: Optional[str]) -> dict:
    """Brevo only sends from verified senders: the configured one, else the account's first active one."""
    if configured:
        return {"email": configured, "name": "Nova status"}
    for sender in senders:
        if sender.get("active"):
            return {"email": sender["email"], "name": "Nova status"}
    raise RuntimeError("no active Brevo sender on the account; verify one or set STATUS_REPORT_SENDER")


def fetch_senders(http, api_key: str) -> list[dict]:
    resp = http.get(BREVO_SENDERS_URL, headers={"api-key": api_key, "accept": "application/json"})
    if resp.status_code != 200:
        raise RuntimeError(f"Brevo senders lookup failed: HTTP {resp.status_code} {resp.text[:200]}")
    return resp.json().get("senders", [])


def send_email(http, api_key: str, sender: dict, recipients: list[str], subject: str, html_body: str) -> None:
    resp = http.post(
        BREVO_SEND_URL,
        json={"sender": sender, "to": [{"email": r} for r in recipients], "subject": subject, "htmlContent": html_body},
        headers={"api-key": api_key, "accept": "application/json", "content-type": "application/json"},
    )
    if resp.status_code != 201:
        raise RuntimeError(f"Brevo rejected the status email: HTTP {resp.status_code} {resp.text[:200]}")


# ── Google Cloud reads ───────────────────────────────────────────────


class Gcp:
    """Read-only Google Cloud REST access with the job's service-account token (or ACCESS_TOKEN locally)."""

    def __init__(self, now: datetime, token: Optional[str] = None, http: Optional[httpx.Client] = None):
        self.now, self._token, self.http = now, token, http or httpx.Client(timeout=60)

    def headers(self) -> dict:
        token = self._token or self.http.get(METADATA_TOKEN_URL, headers={"Metadata-Flavor": "Google"}).json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    def get(self, url: str, params: Optional[dict] = None) -> dict:
        resp = self.http.get(url, headers=self.headers(), params=params)
        resp.raise_for_status()
        return resp.json()

    def post(self, url: str, body: dict) -> dict:
        resp = self.http.post(url, headers=self.headers(), json=body)
        resp.raise_for_status()
        return resp.json()

    def series(self, metric_filter, aligner, reducer=None, group_by=(), period_s=86400, hours=24) -> dict:
        """Points per series (keyed by the group_by label values), oldest first."""
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        params = {
            "filter": metric_filter,
            "interval.startTime": (self.now - timedelta(hours=hours)).strftime(fmt),
            "interval.endTime": self.now.strftime(fmt),
            "aggregation.alignmentPeriod": f"{period_s}s",
            "aggregation.perSeriesAligner": aligner,
        }
        if reducer:
            params["aggregation.crossSeriesReducer"] = reducer
            params["aggregation.groupByFields"] = list(group_by)
        out: dict = {}
        for s in self.get(f"{MONITORING}/timeSeries", params).get("timeSeries", []):
            labels = {**s.get("resource", {}).get("labels", {}), **s.get("metric", {}).get("labels", {})}
            key = tuple(labels.get(g.rsplit(".", 1)[-1]) for g in group_by)
            points = sorted(s.get("points", []), key=lambda p: p["interval"]["endTime"])
            values = [p["value"].get("doubleValue", p["value"].get("int64Value")) for p in points]
            out[key] = [float(v) for v in values if v is not None]
        return out


def _values(series: dict) -> list[float]:
    return [v for points in series.values() for v in points]


def _try(notes: list[str], what: str, read: Callable):
    try:
        return read()
    except Exception as e:  # noqa: BLE001 - one unreadable source must not stop the email
        logger.warning(f"status report: could not read {what}: {e}")
        notes.append(f"Could not read {what}: {str(e)[:160]}")
        return None


def _peak(gcp, flt, aligner="ALIGN_MAX", reducer=None, scale=1.0):
    vals = _values(gcp.series(flt, aligner, reducer, period_s=300))
    return max(vals) * scale if vals else None


def _percentile(gcp, flt, scale=1.0):
    """p95 of a distribution metric over the whole window, across every revision."""
    vals = _values(gcp.series(flt, "ALIGN_DELTA", "REDUCE_PERCENTILE_95"))
    return max(vals) * scale if vals else None


def _total(gcp, flt):
    """A counter's 24 h total. No series means nothing was counted: a true zero, not missing data."""
    return sum(_values(gcp.series(flt, "ALIGN_SUM", "REDUCE_SUM")))


def _share(limit: Optional[float], fraction: float) -> Optional[float]:
    return limit * fraction if limit else None


# ── Collectors: one section each ─────────────────────────────────────

RUN = 'resource.type="cloud_run_revision" AND resource.label.service_name="{name}"'
SERVICES = [
    ("Prod API", "nova-manager", False),
    ("Prod worker", "nova-manager-worker", True),
    ("Staging API", "nova-manager-staging", False),
    ("Staging worker", "nova-manager-worker-staging", True),
]


def collect_cloud_run(gcp, title: str, name: str, is_worker: bool) -> Section:
    notes: list[str] = []
    svc = _try(notes, f"{name} service", lambda: gcp.get(
        f"https://{REGION}-run.googleapis.com/apis/serving.knative.dev/v1/namespaces/{PROJECT}/services/{name}")) or {}
    template = svc.get("spec", {}).get("template", {})
    annotations = template.get("metadata", {}).get("annotations", {})
    limits = (template.get("spec", {}).get("containers") or [{}])[0].get("resources", {}).get("limits", {})
    max_instances = annotations.get("autoscaling.knative.dev/maxScale")
    status = svc.get("status", {})
    ready = next((c.get("status") == "True" for c in status.get("conditions", []) if c.get("type") == "Ready"), None)
    plan = (f"{limits.get('cpu', '?')} vCPU / {limits.get('memory', '?')}, "
            f"{annotations.get('autoscaling.knative.dev/minScale', '0')}-{max_instances or '?'} instances, "
            f"revision {status.get('latestReadyRevisionName', 'unknown')}")
    if ready is False:
        notes.append(f"{name} is not Ready: its latest revision is not serving.")

    f = RUN.format(name=name)
    readings = [Reading("Serving", None if ready is None else float(ready), text="yes" if ready else "NO",
                        warn=1, crit=1, lower_is_worse=True)]
    if is_worker:
        readings += [
            Reading("Jobs completed", _try(notes, f"{name} jobs", lambda: _total(
                gcp, 'metric.type="logging.googleapis.com/user/nova_worker_jobs_ok" AND ' + f))),
            Reading("ClickHouse insert failures", _try(notes, f"{name} insert failures", lambda: _total(
                gcp, 'metric.type="logging.googleapis.com/user/nova_clickhouse_insert_failed" AND ' + f)), warn=1, crit=100),
        ]
    else:
        by_class = _try(notes, f"{name} request counts", lambda: gcp.series(
            f + ' AND metric.type="run.googleapis.com/request_count"', "ALIGN_SUM", "REDUCE_SUM",
            ["metric.label.response_code_class"]))
        total = sum(_values(by_class)) if by_class is not None else None
        errors = sum(v for key, points in (by_class or {}).items() if key[0] == "5xx" for v in points)
        readings += [
            Reading("Requests", total),
            Reading("5xx error rate", round(errors / total * 100, 2) if total else None, "%", warn=2, crit=5),
            Reading("Latency p95", _try(notes, f"{name} latency", lambda: _percentile(
                gcp, f + ' AND metric.type="run.googleapis.com/request_latencies"')), " ms", warn=2000, crit=5000),
        ]
    cap = float(max_instances) if max_instances else None
    readings += [
        # Active instances per revision: the metric also counts idle ones, and during a deploy the old
        # and new revisions both report, so either sum overstates what one revision ran.
        Reading("Peak instances", _try(notes, f"{name} instances", lambda: max(_values(gcp.series(
            f + ' AND metric.type="run.googleapis.com/container/instance_count" AND metric.label.state="active"',
            "ALIGN_MAX", "REDUCE_SUM",
            ["resource.label.revision_name"], period_s=300)), default=None)),
            f" of {max_instances}" if max_instances else "", warn=_share(cap, 0.8), crit=cap),
        Reading("CPU p95", _try(notes, f"{name} CPU", lambda: _percentile(
            gcp, f + ' AND metric.type="run.googleapis.com/container/cpu/utilizations"', 100)), "%", warn=70, crit=85),
        Reading("Memory p95", _try(notes, f"{name} memory", lambda: _percentile(
            gcp, f + ' AND metric.type="run.googleapis.com/container/memory/utilizations"', 100)), "%", warn=75, crit=90),
    ]
    return Section(f"{title} ({name})", plan, readings, notes)


VM = 'resource.type="gce_instance" AND metric.label.instance_name="{name}"'


def collect_vm(gcp, title: str, name: str, zone: str, data_vm: bool) -> Section:
    notes: list[str] = []
    base = f"https://compute.googleapis.com/compute/v1/projects/{PROJECT}/zones/{zone}"
    inst = _try(notes, f"{name} instance", lambda: gcp.get(f"{base}/instances/{name}")) or {}
    machine = inst.get("machineType", "").rsplit("/", 1)[-1] or "unknown"
    mtype = (_try(notes, f"{name} machine type", lambda: gcp.get(f"{base}/machineTypes/{machine}")) if inst else None) or {}
    memory_gb = mtype.get("memoryMb", 0) / 1024 or None
    disks = ", ".join(f"{d.get('diskSizeGb')} GB" for d in inst.get("disks", [])) or "?"
    plan = (f"{machine}: {mtype.get('guestCpus', '?')} vCPU, {f'{memory_gb:.0f} GB' if memory_gb else '?'} RAM, "
            f"disk {disks}, status {inst.get('status', 'unknown')}")
    if inst and inst.get("status") != "RUNNING":
        notes.append(f"{name} is {inst.get('status')}, not RUNNING.")

    f = VM.format(name=name)
    cpu = _try(notes, f"{name} CPU", lambda: _values(gcp.series(
        f + ' AND metric.type="compute.googleapis.com/instance/cpu/utilization"', "ALIGN_MEAN", period_s=300)))
    readings = [
        Reading("CPU average", sum(cpu) / len(cpu) * 100 if cpu else None, "%", warn=60, crit=80),
        Reading("CPU peak (5 min)", max(cpu) * 100 if cpu else None, "%"),
    ]
    if data_vm:
        used = _try(notes, f"{name} memory", lambda: _peak(
            gcp, f + ' AND metric.type="compute.googleapis.com/guest/memory/bytes_used" AND metric.label.state="used"'))
        disk = _try(notes, f"{name} disk", lambda: gcp.series(
            f + ' AND metric.type="compute.googleapis.com/guest/disk/bytes_used" AND metric.label.device_name="sda1"',
            "ALIGN_MAX", group_by=["metric.label.state"], period_s=300)) or {}
        disk_used, disk_free = disk.get(("used",), []), disk.get(("free",), [])
        disk_total = (disk_used[-1] + disk_free[-1]) / 1e9 if disk_used and disk_free else None
        readings += [
            Reading("Memory used peak", used / 1e9 if used is not None else None,
                    f" GB of {memory_gb:.0f} GB" if memory_gb else " GB", warn=_share(memory_gb, 0.75), crit=_share(memory_gb, 0.85)),
            Reading("Data disk used now", disk_used[-1] / 1e9 if disk_used else None,
                    f" GB of {disk_total:.1f} GB" if disk_total else " GB", warn=_share(disk_total, 0.7), crit=_share(disk_total, 0.8)),
            Reading("Data disk peak", max(disk_used) / 1e9 if disk_used else None, " GB",
                    warn=_share(disk_total, 0.7), crit=_share(disk_total, 0.8)),
            Reading("ClickHouse/Redis out-of-memory kills", _try(
                notes, f"{name} out-of-memory kills", lambda: _count_oom_kills(gcp, inst.get("id"))), warn=1, crit=1),
        ]
    return Section(f"{title} ({name})", plan, readings, notes)


def _count_oom_kills(gcp, instance_id, max_pages: int = 50) -> float:
    """Kernel OOM kills on the VM. The Logging API can return an empty page that still has a
    nextPageToken when matches are sparse, so every page is read."""
    since = (gcp.now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    request = {
        "resourceNames": [f"projects/{PROJECT}"], "pageSize": 1000,
        # The kernel journal log and its message field keep the search narrow; a free-text search
        # over every log of the VM sometimes failed with HTTP 500.
        "filter": f'logName="projects/{PROJECT}/logs/cos_journal_warning" AND resource.type="gce_instance" '
                  f'AND resource.labels.instance_id="{instance_id}" '
                  f'AND jsonPayload.MESSAGE:"Out of memory: Killed process" AND timestamp>="{since}"',
    }
    kills = 0
    for _ in range(max_pages):
        page = gcp.post("https://logging.googleapis.com/v2/entries:list", request)
        kills += len(page.get("entries", []))
        if not page.get("nextPageToken"):
            return float(kills)
        request["pageToken"] = page["nextPageToken"]
    raise RuntimeError(f"more than {max_pages} pages of log results; count incomplete")


DB = f'resource.type="cloudsql_database" AND resource.label.database_id="{PROJECT}:nova-db"'


def collect_cloud_sql(gcp) -> Section:
    notes: list[str] = []
    inst = _try(notes, "nova-db settings", lambda: gcp.get(
        f"https://sqladmin.googleapis.com/v1/projects/{PROJECT}/instances/nova-db")) or {}
    settings = inst.get("settings", {})
    backups = settings.get("backupConfiguration", {}).get("enabled")
    flags = {fl.get("name"): fl.get("value") for fl in settings.get("databaseFlags", [])}
    max_conn = int(flags["max_connections"]) if flags.get("max_connections") else None
    plan = (f"{settings.get('tier', 'unknown tier')}, {settings.get('dataDiskSizeGb', '?')} GB SSD, "
            f"automatic backups {'ON' if backups else 'OFF' if backups is False else 'unknown'}, "
            f"max_connections {max_conn or 'default'}, state {inst.get('state', 'unknown')}")
    if backups is False:
        notes.append("Automatic backups are disabled: a lost or corrupted database cannot be restored.")

    cpu = _try(notes, "nova-db CPU", lambda: _values(gcp.series(
        DB + ' AND metric.type="cloudsql.googleapis.com/database/cpu/utilization"', "ALIGN_MEAN", period_s=300)))
    up = _try(notes, "nova-db availability", lambda: _values(gcp.series(
        DB + ' AND metric.type="cloudsql.googleapis.com/database/up"', "ALIGN_MIN", period_s=300)))
    readings = [
        Reading("CPU average", sum(cpu) / len(cpu) * 100 if cpu else None, "%", warn=60, crit=80),
        Reading("CPU peak", max(cpu) * 100 if cpu else None, "%", warn=70, crit=80),
        Reading("Memory peak", _try(notes, "nova-db memory", lambda: _peak(
            gcp, DB + ' AND metric.type="cloudsql.googleapis.com/database/memory/utilization"', scale=100)), "%", warn=75, crit=85),
        Reading("Connections peak", _try(notes, "nova-db connections", lambda: _peak(
            gcp, DB + ' AND metric.type="cloudsql.googleapis.com/database/postgresql/num_backends"', "ALIGN_MAX", "REDUCE_SUM")),
            f" of {max_conn}" if max_conn else "", warn=_share(max_conn, 2 / 3), crit=_share(max_conn, 0.8)),
        Reading("Disk used", _try(notes, "nova-db disk", lambda: _peak(
            gcp, DB + ' AND metric.type="cloudsql.googleapis.com/database/disk/utilization"', scale=100)), "%", warn=70, crit=85),
        Reading("Minutes down", float(sum(5 for v in up if v < 1)) if up else None, " min", warn=1, crit=15),
    ]
    return Section("Cloud SQL Postgres (nova-db)", plan, readings, notes)


def collect_uptime(gcp) -> Section:
    notes: list[str] = []
    passed = _try(notes, "uptime check", lambda: _values(gcp.series(
        'resource.type="uptime_url" AND metric.type="monitoring.googleapis.com/uptime_check/check_passed"',
        "ALIGN_FRACTION_TRUE", period_s=300)))
    return Section("Public API health (api.nova.xgaming.club/health)", "Google uptime check every 60 s", [
        Reading("Checks passing", sum(passed) / len(passed) * 100 if passed else None, "%",
                warn=99.9, crit=99.0, lower_is_worse=True),
    ], notes)


def collect_alerts(gcp, now: datetime) -> list[dict]:
    since = (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    alerts = gcp.get(f"{MONITORING}/alerts", {"pageSize": 100, "orderBy": "open_time desc"}).get("alerts", [])

    def stamp(t):
        return t[:16].replace("T", " ") if t else "still open"

    return [{"opened": stamp(a.get("openTime")), "closed": stamp(a.get("closeTime")), "name": a["policy"]["displayName"]}
            for a in alerts if a.get("openTime", "") >= since]


def _named(name: str, collect: Callable) -> Callable:
    collect.__name__ = name
    return collect


COLLECTORS: list[Callable] = [
    *[_named(f"{title} ({name})", lambda gcp, t=title, n=name, w=worker: collect_cloud_run(gcp, t, n, w))
      for title, name, worker in SERVICES],
    _named("Data VM (nova-data)", lambda gcp: collect_vm(gcp, "Data VM: ClickHouse + Redis", "nova-data", f"{REGION}-a", True)),
    _named("Notice service VM (notice-service)", lambda gcp: collect_vm(
        gcp, "Notice service VM", "notice-service", f"{REGION}-c", False)),
    collect_cloud_sql,
    collect_uptime,
]


def build_report(gcp, now: datetime) -> Report:
    sections = []
    for collect in COLLECTORS:
        try:
            sections.append(collect(gcp))
        except Exception as e:  # noqa: BLE001 - a broken section must not stop the rest of the email
            name = getattr(collect, "__name__", "Section")
            logger.error(f"status report: section {name} failed: {e}")
            sections.append(Section(name, "unknown", [Reading("Section data", None)],
                                    [f"Could not build this section: {str(e)[:200]}"]))
    notes: list[str] = []
    alerts = _try(notes, "fired alerts", lambda: collect_alerts(gcp, now))
    if alerts is None:
        sections.append(Section("Alerts", "Cloud Monitoring", [Reading("Alert history", None)], notes))
    return Report(now, sections, alerts or [])
