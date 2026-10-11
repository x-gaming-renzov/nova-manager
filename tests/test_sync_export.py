"""Sync export API: lets a downstream service mirror the ClickHouse analytics tables.

Covers the query builders, the controller's paging/empty/failure behaviour and the HTTP
contract. ClickHouse is replaced by a fake that records the SQL and parameters it is given.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nova_manager.api.sync.router import router as sync_router
from nova_manager.components.auth.dependencies import require_app_context
from nova_manager.components.metrics.artefacts import EventsArtefacts
from nova_manager.components.sync import export_controller
from nova_manager.components.sync.query_builder import (
    build_digest_query,
    build_rows_query,
    build_summary_query,
)
from nova_manager.components.sync.tables import SYNC_TABLES
from nova_manager.core.enums import UserRole
from nova_manager.core.security import AuthContext

ORG_ID = "11111111-1111-1111-1111-111111111111"
APP_ID = "22222222-2222-2222-2222-222222222222"
DB = EventsArtefacts(ORG_ID, APP_ID).database_name
WATERMARK = "2026-10-11 12:00:00.000000"
TS = "2026-10-11 11:59:00.123456"
ROW_ID = "3cc3f7f1-6075-414b-8975-bbdb2dbba6fa"


# ── Table catalogue ─────────────────────────────────────────


def test_all_five_clickhouse_tables_are_exported():
    assert set(SYNC_TABLES) == {
        "raw_events",
        "event_props",
        "user_profile_props",
        "user_experience",
        "business_metrics",
    }


def test_only_the_replacing_table_is_read_with_final():
    # business_metrics is ReplacingMergeTree: without FINAL a superseded value is exported too.
    assert [name for name, table in SYNC_TABLES.items() if table.final] == ["business_metrics"]


# ── Rows query ──────────────────────────────────────────────


def test_first_page_has_no_cursor_condition():
    sql, params = build_rows_query(SYNC_TABLES["raw_events"], DB, until=WATERMARK, limit=100)
    assert f"FROM {DB}.raw_events" in sql
    assert "(_written_at, _row_id) >" not in sql
    assert "after_ts" not in params and "after_id" not in params


def test_next_page_resumes_strictly_after_the_cursor_pair():
    sql, params = build_rows_query(
        SYNC_TABLES["raw_events"], DB, until=WATERMARK, limit=100, after_ts=TS, after_id=ROW_ID
    )
    # Rows inserted in one block share _written_at, so the row id must break the tie.
    assert "(_written_at, _row_id) > (parseDateTime64BestEffort({after_ts:String}, 6, 'UTC'), toUUID({after_id:String}))" in sql
    assert params["after_ts"] == TS and params["after_id"] == ROW_ID


def test_the_cursor_also_bounds_write_time_alone_so_the_index_can_skip_old_parts():
    # ClickHouse does not use the minmax index for a tuple comparison; without the plain bound
    # every page would scan the whole table.
    sql, _ = build_rows_query(
        SYNC_TABLES["raw_events"], DB, until=WATERMARK, limit=100, after_ts=TS, after_id=ROW_ID
    )
    assert "_written_at >= parseDateTime64BestEffort({after_ts:String}, 6, 'UTC')" in sql


def test_rows_are_ordered_by_write_time_then_row_id():
    sql, _ = build_rows_query(SYNC_TABLES["event_props"], DB, until=WATERMARK, limit=100)
    assert "ORDER BY _written_at, _row_id" in sql


def test_rows_newer_than_the_watermark_are_withheld():
    sql, params = build_rows_query(SYNC_TABLES["raw_events"], DB, until=WATERMARK, limit=100)
    assert "_written_at <= parseDateTime64BestEffort({until:String}, 6, 'UTC')" in sql
    assert params["until"] == WATERMARK


def test_one_extra_row_is_fetched_to_detect_a_further_page():
    _, params = build_rows_query(SYNC_TABLES["raw_events"], DB, until=WATERMARK, limit=100)
    assert params["limit"] == 101


def test_day_filter_selects_one_utc_day_of_write_time():
    sql, params = build_rows_query(
        SYNC_TABLES["raw_events"], DB, until=WATERMARK, limit=100, day="2026-10-10"
    )
    assert "toDate(_written_at, 'UTC') = toDate({day:String})" in sql
    assert params["day"] == "2026-10-10"


def test_every_data_column_and_the_three_sync_fields_are_selected():
    sql, _ = build_rows_query(SYNC_TABLES["user_experience"], DB, until=WATERMARK, limit=10)
    for column in SYNC_TABLES["user_experience"].columns:
        assert column in sql
    for field in ("AS _row_id", "AS _written_at", "AS _row_hash"):
        assert field in sql


def test_row_hash_covers_every_data_column_in_order():
    sql, _ = build_rows_query(SYNC_TABLES["user_profile_props"], DB, until=WATERMARK, limit=10)
    assert "cityHash64(user_id, key, value, server_ts)" in sql


def test_business_metrics_rows_are_read_with_final():
    sql, _ = build_rows_query(SYNC_TABLES["business_metrics"], DB, until=WATERMARK, limit=10)
    assert f"FROM {DB}.business_metrics FINAL" in sql


def test_plain_tables_are_not_read_with_final():
    sql, _ = build_rows_query(SYNC_TABLES["raw_events"], DB, until=WATERMARK, limit=10)
    assert "FINAL" not in sql


def test_request_values_are_bound_never_interpolated():
    hostile = "x'; DROP TABLE raw_events; --"
    sql, params = build_rows_query(
        SYNC_TABLES["raw_events"], DB, until=hostile, limit=5, after_ts=hostile, after_id=hostile, day=hostile
    )
    assert hostile not in sql
    assert list(params.values()).count(hostile) == 4


# ── Digest and summary queries ──────────────────────────────


def test_digest_groups_by_utc_day_with_count_and_checksum():
    sql, _ = build_digest_query(SYNC_TABLES["raw_events"], DB, until=WATERMARK)
    assert "toDate(_written_at, 'UTC')" in sql
    assert "count() AS row_count" in sql
    assert "sum(cityHash64(event_id, user_id, event_name, event_data, client_ts, server_ts))" in sql
    assert "GROUP BY day" in sql and "ORDER BY day" in sql


def test_digest_uses_the_same_hash_expression_as_the_rows():
    # PB sums the per-row hashes it was given; the two must be the same function of the same columns.
    table = SYNC_TABLES["event_props"]
    rows_sql, _ = build_rows_query(table, DB, until=WATERMARK, limit=1)
    digest_sql, _ = build_digest_query(table, DB, until=WATERMARK)
    hash_expression = f"cityHash64({', '.join(table.columns)})"
    assert hash_expression in rows_sql and hash_expression in digest_sql


def test_digest_is_bounded_by_the_watermark_and_the_day_range():
    sql, params = build_digest_query(
        SYNC_TABLES["raw_events"], DB, until=WATERMARK, from_day="2026-10-01", to_day="2026-10-11"
    )
    assert "_written_at <= parseDateTime64BestEffort({until:String}, 6, 'UTC')" in sql
    assert "toDate(_written_at, 'UTC') >= toDate({from_day:String})" in sql
    assert "toDate(_written_at, 'UTC') <= toDate({to_day:String})" in sql
    assert params == {"until": WATERMARK, "from_day": "2026-10-01", "to_day": "2026-10-11"}


def test_digest_without_a_range_covers_every_day():
    sql, params = build_digest_query(SYNC_TABLES["raw_events"], DB, until=WATERMARK)
    assert "from_day" not in sql and "to_day" not in sql
    assert params == {"until": WATERMARK}


def test_business_metrics_digest_is_read_with_final():
    sql, _ = build_digest_query(SYNC_TABLES["business_metrics"], DB, until=WATERMARK)
    assert f"FROM {DB}.business_metrics FINAL" in sql


def test_summary_counts_rows_up_to_the_watermark():
    sql, params = build_summary_query(SYNC_TABLES["raw_events"], DB, until=WATERMARK)
    assert "count() AS row_count" in sql and "AS max_written_at" in sql
    assert params == {"until": WATERMARK}


# ── HTTP contract ───────────────────────────────────────────


class FakeClickHouse:
    """Stands in for ClickHouseService: answers by the kind of query, records what it was asked."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.rows: list[dict] = []
        self.digest: list[dict] = []
        self.summary: list[dict] = [{"row_count": 0, "max_written_at": ""}]
        self.error: Exception | None = None

    def run_query(self, query: str, parameters: dict | None = None) -> list[dict]:
        self.calls.append((query, parameters or {}))
        if "AS watermark" in query:
            return [{"watermark": WATERMARK}]
        if self.error is not None:
            raise self.error
        if "GROUP BY day" in query:
            return self.digest
        if "AS max_written_at" in query:
            return self.summary
        return self.rows[: (parameters or {}).get("limit", len(self.rows))]

    def data_calls(self):
        return [call for call in self.calls if "AS watermark" not in call[0]]


def _auth(org=ORG_ID, app=APP_ID):
    return AuthContext(
        auth_user_id="u1", organisation_id=org, app_id=app, email="svc@example.com", role=UserRole.OWNER
    )


@pytest.fixture
def fake(monkeypatch):
    clickhouse = FakeClickHouse()
    monkeypatch.setattr(export_controller, "ClickHouseService", lambda: clickhouse)
    return clickhouse


@pytest.fixture
def client(fake):
    app = FastAPI()
    app.include_router(sync_router, prefix="/api/v1/sync")
    app.dependency_overrides[require_app_context] = _auth
    return TestClient(app)


def _row(n: int) -> dict:
    return {
        "event_id": f"e{n}",
        "user_id": "u",
        "event_name": "open",
        "event_data": "{}",
        "client_ts": "2026-10-11 11:00:00.000",
        "server_ts": "2026-10-11 11:00:00.000",
        "_row_id": f"00000000-0000-0000-0000-{n:012d}",
        "_written_at": f"2026-10-11 11:00:00.{n:06d}",
        "_row_hash": str(1000 + n),
    }


def test_rows_page_returns_rows_cursor_and_watermark(client, fake):
    fake.rows = [_row(1), _row(2)]
    body = client.get("/api/v1/sync/raw_events/rows/?limit=5").json()
    assert body["rows"] == [_row(1), _row(2)]
    assert body["has_more"] is False
    assert body["next_cursor"] == {"after_ts": _row(2)["_written_at"], "after_id": _row(2)["_row_id"]}
    assert body["watermark"] == WATERMARK


def test_a_full_page_reports_more_and_drops_the_lookahead_row(client, fake):
    fake.rows = [_row(1), _row(2), _row(3)]
    body = client.get("/api/v1/sync/raw_events/rows/?limit=2").json()
    assert [row["event_id"] for row in body["rows"]] == ["e1", "e2"]
    assert body["has_more"] is True
    assert body["next_cursor"]["after_id"] == _row(2)["_row_id"]


def test_an_empty_page_has_no_cursor_so_the_caller_keeps_its_own(client, fake):
    body = client.get("/api/v1/sync/raw_events/rows/").json()
    assert body == {"rows": [], "next_cursor": None, "has_more": False, "watermark": WATERMARK}


def test_the_database_comes_from_the_token_not_the_request(client, fake):
    client.get("/api/v1/sync/raw_events/rows/?organisation_id=other&app_id=other")
    query, _ = fake.data_calls()[0]
    assert f"FROM {DB}.raw_events" in query


def test_another_apps_token_reads_another_database(fake):
    app = FastAPI()
    app.include_router(sync_router, prefix="/api/v1/sync")
    other_app = "33333333-3333-3333-3333-333333333333"
    app.dependency_overrides[require_app_context] = lambda: _auth(app=other_app)
    TestClient(app).get("/api/v1/sync/raw_events/rows/")
    query, _ = fake.data_calls()[0]
    assert f"FROM {EventsArtefacts(ORG_ID, other_app).database_name}.raw_events" in query
    assert f"FROM {DB}.raw_events" not in query


def test_the_cursor_and_day_reach_the_query_as_parameters(client, fake):
    client.get(f"/api/v1/sync/event_props/rows/?after_ts={TS}&after_id={ROW_ID}&day=2026-10-10&limit=7")
    _, params = fake.data_calls()[0]
    assert params["after_ts"] == TS and params["after_id"] == ROW_ID
    assert params["day"] == "2026-10-10" and params["limit"] == 8


def test_requests_without_a_token_are_refused():
    app = FastAPI()
    app.include_router(sync_router, prefix="/api/v1/sync")
    response = TestClient(app).get("/api/v1/sync/raw_events/rows/")
    assert response.status_code in (401, 403)


@pytest.mark.parametrize("name", ["nope", "raw_events;DROP", "system.tables", "RAW_EVENTS"])
def test_unknown_table_names_are_not_found_and_never_queried(client, fake, name):
    assert client.get(f"/api/v1/sync/{name}/rows/").status_code == 404
    assert client.get(f"/api/v1/sync/{name}/digest/").status_code == 404
    assert fake.calls == []


@pytest.mark.parametrize("limit", ["0", "-1", "10001", "abc"])
def test_limits_outside_one_to_the_maximum_are_rejected(client, fake, limit):
    assert client.get(f"/api/v1/sync/raw_events/rows/?limit={limit}").status_code == 422
    assert fake.calls == []


@pytest.mark.parametrize(
    "query",
    [
        f"after_ts={TS}",  # half a cursor
        f"after_id={ROW_ID}",  # the other half
        f"after_ts=yesterday&after_id={ROW_ID}",
        f"after_ts={TS}&after_id=not-a-uuid",
        "day=2026-13-40",
        "day=11-10-2026",
        "until=soon",
    ],
)
def test_malformed_cursor_day_or_until_is_rejected(client, fake, query):
    assert client.get(f"/api/v1/sync/raw_events/rows/?{query}").status_code == 422
    assert fake.calls == []


def test_digest_returns_one_entry_per_day(client, fake):
    fake.digest = [{"day": "2026-10-10", "row_count": 3, "checksum": "42"}]
    body = client.get("/api/v1/sync/raw_events/digest/?from=2026-10-01&to=2026-10-11").json()
    assert body == {"days": [{"day": "2026-10-10", "row_count": 3, "checksum": "42"}], "watermark": WATERMARK}
    _, params = fake.data_calls()[0]
    assert params["from_day"] == "2026-10-01" and params["to_day"] == "2026-10-11"


@pytest.mark.parametrize("query", ["from=2026-10-12&to=2026-10-11", "from=bad", "to=2026-02-30"])
def test_digest_rejects_a_reversed_or_malformed_range(client, fake, query):
    assert client.get(f"/api/v1/sync/raw_events/digest/?{query}").status_code == 422
    assert fake.calls == []


def test_tables_lists_every_table_with_its_row_count(client, fake):
    fake.summary = [{"row_count": 9, "max_written_at": TS}]
    body = client.get("/api/v1/sync/tables/").json()
    assert body["watermark"] == WATERMARK
    assert [table["name"] for table in body["tables"]] == list(SYNC_TABLES)
    assert body["tables"][0] == {"name": "raw_events", "row_count": 9, "max_written_at": TS}


@pytest.mark.parametrize(
    "message",
    [
        "Code: 81. DB::Exception: Database x does not exist. (UNKNOWN_DATABASE)",
        "Code: 60. DB::Exception: Unknown table expression identifier 'x.raw_events' (UNKNOWN_TABLE)",
    ],
)
def test_an_app_that_has_tracked_nothing_reads_as_empty(client, fake, message):
    # A new app has no database (or no business_metrics table) yet: that is "no rows", not a failure.
    fake.error = Exception(message)
    assert client.get("/api/v1/sync/raw_events/rows/").json()["rows"] == []
    assert client.get("/api/v1/sync/raw_events/digest/").json()["days"] == []
    tables = client.get("/api/v1/sync/tables/").json()["tables"]
    assert all(table["row_count"] == 0 and table["max_written_at"] is None for table in tables)


def test_tables_without_marker_columns_fail_loudly_instead_of_exporting(client, fake):
    # Before the marker migration has run the export would be unordered and unrepeatable.
    fake.error = Exception("Code: 47. DB::Exception: Unknown expression identifier '_written_at' (UNKNOWN_IDENTIFIER)")
    response = client.get("/api/v1/sync/raw_events/rows/")
    assert response.status_code == 503
    assert "marker" in response.json()["detail"].lower()


def test_clickhouse_being_unreachable_is_a_503_not_a_partial_page(client, fake):
    fake.error = ConnectionError("connection refused")
    response = client.get("/api/v1/sync/raw_events/rows/")
    assert response.status_code == 503
    assert "rows" not in response.json()


def test_a_caller_supplied_until_can_only_lower_the_watermark(client, fake):
    client.get("/api/v1/sync/raw_events/rows/?until=2026-10-10 00:00:00.000000")
    watermark_query, params = fake.calls[0]
    assert "least(" in watermark_query
    assert params["until"] == "2026-10-10 00:00:00.000000"
