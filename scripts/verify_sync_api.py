#!/usr/bin/env python3
"""End-to-end proof of the sync export API (/api/v1/sync).

Registers a throwaway organisation, writes analytics data through the public endpoints, then
copies it into a local SQLite mirror the way a downstream service would (incremental pull by
cursor, plus a per-day compare-and-repair) and checks the mirror equals the source.

Usage:
  NOVA_ADMIN_KEY=... python scripts/verify_sync_api.py --base-url http://localhost:8000 \
      --lag 30 [--clickhouse-url http://localhost:8123]

--lag must be at least the server's SYNC_WATERMARK_LAG_SECONDS: new rows are withheld that long.
--clickhouse-url enables the checks that need direct access (independent row counts and the
manual-delete scenario); leave it out against an environment whose ClickHouse is private.
"""

import argparse
import json
import os
import sqlite3
import sys
import time
import uuid

import requests

RUN_ID = uuid.uuid4().hex[:8]
TABLES = ["raw_events", "event_props", "user_profile_props", "user_experience", "business_metrics"]
# business_metrics is exported deduplicated, so its identity is the metric key, not the row id.
BUSINESS_KEY = ("metric_name", "dimension", "period_start", "scenario_id")
MOD = 2**64

results: list[tuple[bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> bool:
    results.append((passed, name))
    print(("  PASS  " if passed else "  FAIL  ") + name + (f" — {detail}" if detail and not passed else ""))
    return passed


def section(title: str) -> None:
    print(f"\n── {title}")


class Api:
    def __init__(self, base_url: str):
        self.api = base_url.rstrip("/") + "/api/v1"
        self.jwt: dict = {}
        self.sdk: dict = {}

    def register(self, admin_key: str) -> None:
        r = requests.post(
            f"{self.api}/auth/register",
            headers={"X-Nova-Admin-Key": admin_key},
            json={
                "email": f"sync-verify-{RUN_ID}@example.com",
                "password": f"Sync-verify-{RUN_ID}!",
                "name": "Sync Verify",
                "company": f"Sync Verify {RUN_ID}",
            },
            timeout=30,
        )
        r.raise_for_status()
        self.jwt = {"Authorization": f"Bearer {r.json()['access_token']}"}

    def create_app(self, name: str) -> dict:
        """Creates an app and returns headers for a token scoped to it."""
        r = requests.post(f"{self.api}/auth/apps", headers=self.jwt, json={"name": name, "description": name}, timeout=60)
        r.raise_for_status()
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    def use_app(self, headers: dict) -> None:
        self.jwt = headers
        r = requests.get(f"{self.api}/auth/sdk-credentials", headers=headers, timeout=30)
        r.raise_for_status()
        self.sdk = {"Authorization": f"Bearer {r.json()['sdk_api_key']}"}

    def create_user(self, user_id: str, profile: dict) -> None:
        r = requests.post(f"{self.api}/users/create-user/", headers=self.sdk, json={"user_id": user_id, "user_profile": profile}, timeout=30)
        r.raise_for_status()

    def track(self, user_id: str, events: list[dict]) -> None:
        r = requests.post(f"{self.api}/metrics/track-events/", headers=self.sdk, json={"user_id": user_id, "events": events}, timeout=30)
        r.raise_for_status()

    def identify(self, anonymous_id: str, identified_id: str) -> None:
        r = requests.post(f"{self.api}/users/identify/", headers=self.sdk, json={"anonymous_id": anonymous_id, "identified_id": identified_id}, timeout=30)
        r.raise_for_status()

    def business_data(self, items: list[dict]) -> None:
        r = requests.post(f"{self.api}/metrics/business-data/", headers=self.jwt, json={"data": items}, timeout=30)
        r.raise_for_status()

    def get(self, path: str, headers: dict | None = None, **params) -> requests.Response:
        return requests.get(f"{self.api}/sync/{path}", headers=self.jwt if headers is None else headers, params=params, timeout=60)

    def summary(self) -> dict:
        r = self.get("tables/")
        r.raise_for_status()
        return {table["name"]: table for table in r.json()["tables"]}


class CrashAfterPage(Exception):
    pass


class Mirror:
    """A local copy kept the way a downstream service would keep it."""

    def __init__(self, api: Api, page_size: int):
        self.api = api
        self.page_size = page_size
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        for table in TABLES:
            self.db.execute(
                f"CREATE TABLE {table} (pk TEXT PRIMARY KEY, row_id TEXT, written_at TEXT, row_hash TEXT, data TEXT)"
            )
        self.db.execute("CREATE TABLE sync_state (name TEXT PRIMARY KEY, after_ts TEXT, after_id TEXT)")

    @staticmethod
    def _pk(table: str, row: dict) -> str:
        if table == "business_metrics":
            return "|".join(str(row[column]) for column in BUSINESS_KEY)
        return row["_row_id"]

    def _store(self, table: str, rows: list[dict]) -> None:
        self.db.executemany(
            f"INSERT INTO {table} (pk, row_id, written_at, row_hash, data) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(pk) DO UPDATE SET row_id = excluded.row_id, written_at = excluded.written_at, "
            "row_hash = excluded.row_hash, data = excluded.data",
            [(self._pk(table, row), row["_row_id"], row["_written_at"], row["_row_hash"], json.dumps(row)) for row in rows],
        )

    def pull(self, table: str, crash_after_pages: int | None = None, crash_before_commit: bool = False) -> int:
        """Copy every row after the saved cursor. The cursor moves in the same transaction as the rows."""
        copied = pages = 0
        while True:
            cursor = self.db.execute("SELECT after_ts, after_id FROM sync_state WHERE name = ?", (table,)).fetchone()
            params = {"limit": self.page_size}
            if cursor:
                params.update(after_ts=cursor[0], after_id=cursor[1])
            response = self.api.get(f"{table}/rows/", **params)
            response.raise_for_status()
            page = response.json()

            self.db.execute("BEGIN")
            self._store(table, page["rows"])
            if page["next_cursor"]:
                self.db.execute(
                    "INSERT INTO sync_state (name, after_ts, after_id) VALUES (?, ?, ?) "
                    "ON CONFLICT(name) DO UPDATE SET after_ts = excluded.after_ts, after_id = excluded.after_id",
                    (table, page["next_cursor"]["after_ts"], page["next_cursor"]["after_id"]),
                )
            pages += 1
            if crash_before_commit and pages == crash_after_pages:
                self.db.execute("ROLLBACK")
                raise CrashAfterPage()
            self.db.execute("COMMIT")
            copied += len(page["rows"])
            if crash_after_pages is not None and pages == crash_after_pages:
                raise CrashAfterPage()
            if not page["has_more"]:
                return copied

    def _local_digest(self, table: str, until: str) -> dict:
        days: dict[str, list[int]] = {}
        for written_at, row_hash in self.db.execute(f"SELECT written_at, row_hash FROM {table} WHERE written_at <= ?", (until,)):
            entry = days.setdefault(written_at[:10], [0, 0])
            entry[0] += 1
            entry[1] = (entry[1] + int(row_hash)) % MOD
        return {day: (count, str(checksum)) for day, (count, checksum) in days.items()}

    def mismatched_days(self, table: str) -> tuple[list[str], str]:
        response = self.api.get(f"{table}/digest/")
        response.raise_for_status()
        body = response.json()
        source = {entry["day"]: (entry["row_count"], entry["checksum"]) for entry in body["days"]}
        local = self._local_digest(table, body["watermark"])
        return sorted(day for day in set(source) | set(local) if source.get(day) != local.get(day)), body["watermark"]

    def matches(self, table: str) -> bool:
        return self.mismatched_days(table)[0] == []

    def repair(self, table: str) -> list[str]:
        """Replace every day whose count or checksum differs from the source. Returns those days."""
        days, until = self.mismatched_days(table)
        for day in days:
            self.db.execute("BEGIN")
            self.db.execute(f"DELETE FROM {table} WHERE substr(written_at, 1, 10) = ? AND written_at <= ?", (day, until))
            params = {"limit": self.page_size, "day": day, "until": until}
            while True:
                response = self.api.get(f"{table}/rows/", **params)
                response.raise_for_status()
                page = response.json()
                self._store(table, page["rows"])
                if not page["has_more"]:
                    break
                params.update(page["next_cursor"])
            self.db.execute("COMMIT")
        return days

    def count(self, table: str) -> int:
        return self.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    def ids(self, table: str) -> set[str]:
        return {row[0] for row in self.db.execute(f"SELECT pk FROM {table}")}

    def data(self, table: str) -> list[dict]:
        return [json.loads(row[0]) for row in self.db.execute(f"SELECT data FROM {table}")]


def clickhouse(url: str, sql: str) -> str:
    r = requests.post(url, params={"mutations_sync": 2}, data=sql.encode(), timeout=120)
    r.raise_for_status()
    return r.text.strip()


def wait_for(description: str, condition, timeout: int = 90) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(2)
    return check(f"timed out waiting for {description}", False)


def events(name: str, count: int, timestamp: str = "2026-10-01T10:00:00Z", **data) -> list[dict]:
    return [{"event_name": name, "event_data": {"n": i, **data}, "timestamp": timestamp} for i in range(count)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--lag", type=int, default=30, help="server SYNC_WATERMARK_LAG_SECONDS")
    parser.add_argument("--clickhouse-url", default="", help="direct ClickHouse HTTP URL (local only)")
    args = parser.parse_args()
    admin_key = os.environ.get("NOVA_ADMIN_KEY", "")
    if not admin_key:
        print("NOVA_ADMIN_KEY must be set (needed to register the throwaway organisation)")
        return 2

    api = Api(args.base_url)
    print(f"Sync API verification (run {RUN_ID}) against {args.base_url}")
    api.register(admin_key)
    main_app = api.create_app(f"sync-verify-{RUN_ID}")
    api.use_app(main_app)
    user, other, anon, ident = (f"{prefix}_{RUN_ID}" for prefix in ("user", "other", "anon", "ident"))

    def settle(table: str, expected: int) -> None:
        """Wait until the worker has written the rows and the watermark has passed them."""
        wait_for(f"{table} to reach {expected} rows", lambda: api.summary()[table]["row_count"] >= expected, timeout=args.lag + 90)
        # One job writes several tables a few milliseconds apart; let the last of them clear the watermark too.
        time.sleep(3)

    def database() -> str:
        """The ClickHouse database of the app under test, found by one of its own rows."""
        return clickhouse(
            args.clickhouse_url,
            f"SELECT _database FROM merge(REGEXP('^org_'), '^raw_events$') WHERE user_id = '{user}' LIMIT 1",
        )

    # ── 1. Full drain ─────────────────────────────────────
    section("1. Full drain (happy path)")
    api.create_user(user, {"country": "IN", "level": "3"})
    api.create_user(other, {"country": "US"})
    api.track(user, events("open", 12) + events("purchase", 5, amount="9.99"))
    api.track(other, events("open", 8))
    api.business_data([
        {"metric_name": "marketing_spend", "dimension": "google", "value": 100.5, "period_start": "2026-09-01T00:00:00Z", "currency": "USD"},
        {"metric_name": "marketing_spend", "dimension": "meta", "value": 60, "period_start": "2026-09-01T00:00:00Z", "currency": "USD"},
        {"metric_name": "revenue", "dimension": "", "value": 999.99, "period_start": "2026-09-01T00:00:00Z"},
    ])
    settle("raw_events", 25)
    settle("business_metrics", 3)
    mirror = Mirror(api, page_size=7)  # small pages force many cursor hops through rows sharing a write time
    summary_before = api.summary()
    for table in TABLES:
        mirror.pull(table)
        check(f"{table}: mirror matches source count and checksum", mirror.matches(table))
        check(f"{table}: mirror holds at least the rows the summary reported", mirror.count(table) >= summary_before[table]["row_count"],
              f"mirror {mirror.count(table)} < summary {summary_before[table]['row_count']}")
    check("raw_events: exactly the 25 tracked events", mirror.count("raw_events") == 25, f"got {mirror.count('raw_events')}")
    check("event_props: one row per event property", mirror.count("event_props") == 12 + 5 * 2 + 8, f"got {mirror.count('event_props')}")
    check("business_metrics: three rows", mirror.count("business_metrics") == 3, f"got {mirror.count('business_metrics')}")
    check("a second pull with nothing new copies nothing", sum(mirror.pull(table) for table in TABLES) == 0)

    # ── 2. Resume after a crash ───────────────────────────
    section("2. Resume after a crash")
    resumed = Mirror(api, page_size=7)
    try:
        resumed.pull("raw_events", crash_after_pages=2)
    except CrashAfterPage:
        pass
    check("crash after two committed pages leaves exactly those pages", resumed.count("raw_events") == 14, f"got {resumed.count('raw_events')}")
    try:
        resumed.pull("raw_events", crash_after_pages=1, crash_before_commit=True)
    except CrashAfterPage:
        pass
    check("crash before commit leaves rows and cursor untouched", resumed.count("raw_events") == 14, f"got {resumed.count('raw_events')}")
    resumed.pull("raw_events")
    check("resumed mirror has the same rows as the uninterrupted one", resumed.ids("raw_events") == mirror.ids("raw_events"))
    check("resumed mirror matches the source", resumed.matches("raw_events"))

    # ── 3 & 4. Backdated events, and events arriving during a drain ──
    section("3-4. Backdated events and events arriving mid-drain")
    api.track(user, events("backdated", 3, timestamp="2020-01-01T00:00:00Z"))
    early = mirror.pull("raw_events")
    check("rows inside the watermark lag are withheld, not half-delivered", early in (0, 3), f"copied {early}")
    settle("raw_events", 28)
    mirror.pull("raw_events")
    mirror.pull("event_props")
    backdated = [row for row in mirror.data("raw_events") if row["event_name"] == "backdated"]
    check("events with a 2020 client timestamp are picked up by the cursor", len(backdated) == 3, f"got {len(backdated)}")
    check("their client timestamp is preserved", all(row["client_ts"].startswith("2020-01-01") for row in backdated))
    check("raw_events still matches after the late arrivals", mirror.matches("raw_events"))

    # ── 5. Identity merge ─────────────────────────────────
    section("5. Identity merge (anonymous user becomes identified)")
    api.create_user(anon, {"country": "DE"})
    api.track(anon, events("anon_open", 6))
    settle("raw_events", 34)
    for table in TABLES:
        mirror.pull(table)
    check("anonymous rows are in the mirror before the merge", sum(row["user_id"] == anon for row in mirror.data("raw_events")) == 6)
    api.identify(anon, ident)

    def merged() -> bool:
        if args.clickhouse_url:
            return clickhouse(args.clickhouse_url, f"SELECT count() FROM {database()}.raw_events WHERE user_id = '{anon}'") == "0"
        return not mirror.matches("raw_events")
    wait_for("the worker to re-key the anonymous rows", merged)
    time.sleep(args.lag + 3)
    for table in ("raw_events", "event_props", "user_profile_props", "user_experience"):
        mirror.pull(table)
    check("the pull alone delivers the re-keyed copies", sum(row["user_id"] == ident for row in mirror.data("raw_events")) == 6)
    for table in ("raw_events", "event_props", "user_profile_props", "user_experience"):
        mirror.repair(table)
        leftover = sum(row["user_id"] == anon for row in mirror.data(table))
        check(f"{table}: no anonymous rows remain after repair", leftover == 0, f"{leftover} left")
        check(f"{table}: matches the source after repair", mirror.matches(table))
    check("the six events survive the merge exactly once", sum(row["event_name"] == "anon_open" for row in mirror.data("raw_events")) == 6)

    # ── 6. Manual delete ──────────────────────────────────
    section("6. Rows deleted directly in ClickHouse")
    if args.clickhouse_url:
        clickhouse(args.clickhouse_url, f"ALTER TABLE {database()}.raw_events DELETE WHERE event_name = 'purchase'")
        check("the mirror no longer matches once rows are deleted at the source", not mirror.matches("raw_events"))
        check("repair found a day to replace", mirror.repair("raw_events") != [])
        check("deleted rows are gone from the mirror", not any(row["event_name"] == "purchase" for row in mirror.data("raw_events")))
        check("raw_events matches again", mirror.matches("raw_events"))
        check("mirror row count equals a direct ClickHouse count",
              str(mirror.count("raw_events")) == clickhouse(args.clickhouse_url, f"SELECT count() FROM {database()}.raw_events"))
    else:
        print("  SKIP  needs --clickhouse-url (direct access)")

    # ── 7. business_metrics replace ───────────────────────
    section("7. Re-ingesting a business metric replaces it")
    api.business_data([{"metric_name": "marketing_spend", "dimension": "google", "value": 250, "period_start": "2026-09-01T00:00:00Z", "currency": "USD"}])
    time.sleep(args.lag + 3)
    mirror.pull("business_metrics")
    google = [row for row in mirror.data("business_metrics") if row["metric_name"] == "marketing_spend" and row["dimension"] == "google"]
    check("one row for the metric key, carrying the new value", len(google) == 1 and google[0]["value"] == 250, str([row["value"] for row in google]))
    mirror.repair("business_metrics")
    check("business_metrics still has three rows and matches", mirror.count("business_metrics") == 3 and mirror.matches("business_metrics"))

    # ── 8. Empty app, and isolation between apps ──────────
    section("8. An app with no data, and isolation between apps")
    empty_app = api.create_app(f"sync-verify-empty-{RUN_ID}")
    for table in TABLES:
        rows = api.get(f"{table}/rows/", headers=empty_app)
        digest = api.get(f"{table}/digest/", headers=empty_app)
        check(f"{table}: empty app reads as empty", rows.status_code == 200 and rows.json()["rows"] == [] and digest.status_code == 200 and digest.json()["days"] == [],
              f"rows {rows.status_code}, digest {digest.status_code}")
    tables = api.get("tables/", headers=empty_app)
    check("empty app: every table reports zero rows", tables.status_code == 200 and all(t["row_count"] == 0 for t in tables.json()["tables"]))
    check("another app's token cannot see this app's rows", api.get("raw_events/rows/", headers=empty_app).json()["rows"] == [])

    # ── Negative cases ────────────────────────────────────
    section("Negative cases")
    check("no token is refused", api.get("raw_events/rows/", headers={}).status_code in (401, 403))
    check("an SDK key is refused", api.get("raw_events/rows/", headers=api.sdk).status_code in (401, 403))
    check("a garbage token is refused", api.get("raw_events/rows/", headers={"Authorization": "Bearer nope"}).status_code in (401, 403))
    for name in ("nope", "raw_events;DROP TABLE raw_events", "system.tables"):
        check(f"unknown table {name!r} is 404", api.get(f"{name}/rows/").status_code == 404 and api.get(f"{name}/digest/").status_code == 404)
    for limit in (0, -1, 10001, "abc"):
        check(f"limit={limit} is 422", api.get("raw_events/rows/", limit=limit).status_code == 422)
    some_row = mirror.data("raw_events")[0]
    for label, params in {
        "after_ts without after_id": {"after_ts": some_row["_written_at"]},
        "after_id without after_ts": {"after_id": some_row["_row_id"]},
        "after_ts that is not a timestamp": {"after_ts": "yesterday", "after_id": some_row["_row_id"]},
        "after_id that is not a UUID": {"after_ts": some_row["_written_at"], "after_id": "1 OR 1=1"},
        "malformed day": {"day": "2026-13-40"},
        "malformed until": {"until": "soon"},
    }.items():
        check(f"{label} is 422", api.get("raw_events/rows/", **params).status_code == 422)
    check("digest with from later than to is 422", api.get("raw_events/digest/", **{"from": "2026-10-12", "to": "2026-10-11"}).status_code == 422)
    check("the table still exists after the injection attempts", api.get("raw_events/rows/", limit=1).status_code == 200)

    failed = [name for passed, name in results if not passed]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    for name in failed:
        print(f"  FAILED: {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
