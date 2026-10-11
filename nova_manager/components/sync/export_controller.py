from clickhouse_connect.driver.exceptions import OperationalError

from nova_manager.components.metrics.artefacts import EventsArtefacts
from nova_manager.components.sync.query_builder import (
    build_digest_query,
    build_rows_query,
    build_summary_query,
    build_watermark_query,
)
from nova_manager.components.sync.tables import SYNC_TABLES
from nova_manager.core.config import SYNC_WATERMARK_LAG_SECONDS
from nova_manager.service.clickhouse_service import ClickHouseService


class SyncMarkersMissing(Exception):
    """The table predates the marker columns and the migration has not run on it."""


class SyncSourceUnavailable(Exception):
    """ClickHouse could not be reached."""


class SyncExportController(EventsArtefacts):
    """Read-only export of one app's analytics tables, in write order, for a mirror to copy."""

    def __init__(self, organisation_id: str, app_id: str):
        super().__init__(organisation_id, app_id)
        self._clickhouse = ClickHouseService()

    def _run(self, sql: str, params: dict) -> list[dict]:
        try:
            return self._clickhouse.run_query(sql, params)
        except (OperationalError, ConnectionError, OSError) as exc:
            raise SyncSourceUnavailable(str(exc)) from exc
        except Exception as exc:
            message = str(exc)
            # An app that has tracked nothing has no database, and business_metrics only
            # exists after its first ingest. Both mean "no rows", not a failure.
            if "UNKNOWN_DATABASE" in message or "UNKNOWN_TABLE" in message:
                return []
            if "UNKNOWN_IDENTIFIER" in message and ("_written_at" in message or "_row_id" in message):
                raise SyncMarkersMissing(message) from exc
            raise

    def _watermark(self, until: str | None) -> str:
        sql, params = build_watermark_query(SYNC_WATERMARK_LAG_SECONDS, until)
        return self._run(sql, params)[0]["watermark"]

    def tables(self) -> dict:
        watermark = self._watermark(None)
        summaries = []
        for table in SYNC_TABLES.values():
            sql, params = build_summary_query(table, self.database_name, watermark)
            found = self._run(sql, params)
            row_count = found[0]["row_count"] if found else 0
            summaries.append(
                {
                    "name": table.name,
                    "row_count": row_count,
                    "max_written_at": found[0]["max_written_at"] if row_count else None,
                }
            )
        return {"tables": summaries, "watermark": watermark}

    def rows(
        self,
        table_name: str,
        limit: int,
        after_ts: str | None = None,
        after_id: str | None = None,
        day: str | None = None,
        until: str | None = None,
    ) -> dict:
        watermark = self._watermark(until)
        sql, params = build_rows_query(
            SYNC_TABLES[table_name],
            self.database_name,
            until=watermark,
            limit=limit,
            after_ts=after_ts,
            after_id=after_id,
            day=day,
        )
        fetched = self._run(sql, params)
        page = fetched[:limit]
        next_cursor = (
            {"after_ts": page[-1]["_written_at"], "after_id": page[-1]["_row_id"]} if page else None
        )
        return {
            "rows": page,
            "next_cursor": next_cursor,
            "has_more": len(fetched) > limit,
            "watermark": watermark,
        }

    def digest(
        self,
        table_name: str,
        from_day: str | None = None,
        to_day: str | None = None,
        until: str | None = None,
    ) -> dict:
        watermark = self._watermark(until)
        sql, params = build_digest_query(
            SYNC_TABLES[table_name], self.database_name, watermark, from_day, to_day
        )
        return {"days": self._run(sql, params), "watermark": watermark}
