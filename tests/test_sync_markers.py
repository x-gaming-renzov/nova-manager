"""Sync marker columns: every analytics row carries its true write time and a unique id.

New tables are created with them; existing tables get them through an idempotent migration.
"""

import pytest

from nova_manager.components.metrics import events_controller
from nova_manager.components.metrics.events_controller import EventsController
from nova_manager.components.sync import markers
from nova_manager.components.sync.markers import ensure_sync_markers
from nova_manager.components.sync.tables import SYNC_TABLES

ORG_ID = "org-1"
APP_ID = "app-1"


class RecordingClickHouse:
    def __init__(self, parts=0, parts_with_markers=0, existing_tables=None):
        self.statements: list[str] = []
        self.parts = parts
        self.parts_with_markers = parts_with_markers
        self.existing_tables = set(SYNC_TABLES) if existing_tables is None else set(existing_tables)

    def execute(self, statement: str):
        self.statements.append(statement)

    def create_table_if_not_exists(self, ddl: str):
        self.statements.append(ddl)

    def run_query(self, query: str, parameters: dict | None = None) -> list[dict]:
        if "system.tables" in query:
            return [{"name": name} for name in sorted(self.existing_tables)]
        return [{"parts": self.parts, "parts_with_markers": self.parts_with_markers}]


@pytest.mark.parametrize(
    "create",
    [
        "create_raw_events_table",
        "create_event_props_table",
        "create_user_profile_table",
        "create_user_experience_table",
        "create_business_metrics_table",
    ],
)
def test_new_tables_are_created_with_the_marker_columns_and_index(monkeypatch, create):
    clickhouse = RecordingClickHouse()
    monkeypatch.setattr(events_controller, "ClickHouseService", lambda: clickhouse)
    getattr(EventsController(ORG_ID, APP_ID), create)()
    ddl = clickhouse.statements[0]
    assert "_written_at DateTime64(6) MATERIALIZED now64(6)" in ddl
    assert "_row_id UUID MATERIALIZED generateUUIDv4()" in ddl
    assert "INDEX idx_written_at _written_at TYPE minmax" in ddl


def _migrate(clickhouse, monkeypatch):
    monkeypatch.setattr(markers, "ClickHouseService", lambda: clickhouse)
    ensure_sync_markers(EventsController(ORG_ID, APP_ID).database_name)
    return clickhouse.statements


def test_existing_tables_get_the_columns_then_have_old_rows_filled_in(monkeypatch):
    statements = _migrate(RecordingClickHouse(parts=3, parts_with_markers=0), monkeypatch)
    raw = [s for s in statements if ".raw_events " in s]
    assert "ADD COLUMN IF NOT EXISTS _written_at" in raw[0] and "ADD COLUMN IF NOT EXISTS _row_id" in raw[0]
    assert any("MATERIALIZE COLUMN _written_at" in s for s in raw)
    assert any("MATERIALIZE COLUMN _row_id" in s for s in raw)


def test_filling_in_old_rows_waits_for_the_mutation_to_finish(monkeypatch):
    # Until it finishes, old rows get a new value on every read, so the export must not start early.
    statements = _migrate(RecordingClickHouse(parts=3, parts_with_markers=0), monkeypatch)
    materialize = [s for s in statements if "MATERIALIZE COLUMN" in s]
    assert materialize and all("mutations_sync = 2" in s for s in materialize)


def test_a_second_run_does_not_rewrite_parts_that_already_have_markers(monkeypatch):
    statements = _migrate(RecordingClickHouse(parts=3, parts_with_markers=3), monkeypatch)
    assert not any("MATERIALIZE COLUMN" in s for s in statements)


def test_a_run_interrupted_before_the_fill_is_completed_by_the_next_run(monkeypatch):
    # Columns already exist (ADD is a no-op) but some parts still lack stored values.
    statements = _migrate(RecordingClickHouse(parts=3, parts_with_markers=1), monkeypatch)
    assert any("MATERIALIZE COLUMN _row_id" in s for s in statements)


def test_an_empty_table_needs_no_fill(monkeypatch):
    statements = _migrate(RecordingClickHouse(parts=0, parts_with_markers=0), monkeypatch)
    assert not any("MATERIALIZE COLUMN" in s for s in statements)


def test_every_exported_table_is_migrated(monkeypatch):
    statements = _migrate(RecordingClickHouse(parts=1, parts_with_markers=0), monkeypatch)
    for table in SYNC_TABLES:
        assert any(f".{table} ADD COLUMN" in s for s in statements), table


def test_a_table_that_does_not_exist_yet_is_skipped(monkeypatch):
    # business_metrics is created on first ingest; altering a missing table would fail the whole run.
    clickhouse = RecordingClickHouse(parts=1, existing_tables={"raw_events"})
    statements = _migrate(clickhouse, monkeypatch)
    assert any(".raw_events ADD COLUMN" in s for s in statements)
    assert not any(".business_metrics" in s for s in statements)


def test_the_skip_index_is_added_to_existing_tables(monkeypatch):
    statements = _migrate(RecordingClickHouse(parts=1, parts_with_markers=0), monkeypatch)
    assert any("ADD INDEX IF NOT EXISTS idx_written_at _written_at TYPE minmax" in s for s in statements)


def test_the_index_is_built_for_old_rows_when_their_markers_are_filled_in(monkeypatch):
    # ADD INDEX only covers parts written afterwards; old parts would never be skipped.
    statements = _migrate(RecordingClickHouse(parts=3, parts_with_markers=0), monkeypatch)
    assert any("MATERIALIZE INDEX idx_written_at" in s and "mutations_sync = 2" in s for s in statements)


def test_the_index_is_not_rebuilt_when_nothing_needed_filling(monkeypatch):
    statements = _migrate(RecordingClickHouse(parts=3, parts_with_markers=3), monkeypatch)
    assert not any("MATERIALIZE INDEX" in s for s in statements)
