"""Admin-only maintenance endpoints, gated by the shared NOVA_ADMIN_KEY.

Exposes a single destructive cleanup that empties every Nova table — Postgres
relational data and the per-app ClickHouse analytics — so a deployed instance
can be reset to a clean slate over HTTP, without DB shell access. Tables are
TRUNCATEd (emptied), never dropped, so the schema stays intact.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from nova_manager.core.admin_key import require_admin_key
from nova_manager.core.log import logger
from nova_manager.core.models import Base
from nova_manager.database.session import get_db
from nova_manager.service.clickhouse_service import ClickHouseService

# Matches the per-app ClickHouse database naming from EventsArtefacts:
# org_<org>_app_<app>. Anchored so we never touch system or unrelated DBs.
_PER_APP_DB_PATTERN = r"^org_.+_app_.+$"

router = APIRouter()


class CleanupRequest(BaseModel):
    # Preview counts without deleting anything when true.
    dry_run: bool = False


class CleanupResponse(BaseModel):
    dry_run: bool
    postgres: dict[str, int]
    clickhouse: dict[str, int]
    postgres_total: int
    clickhouse_total: int


def _postgres_counts(db: Session) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in Base.metadata.sorted_tables:
        result = db.execute(text(f'SELECT count(*) FROM "{table.name}"'))
        counts[table.name] = int(result.scalar() or 0)
    return counts


def _truncate_postgres(db: Session) -> None:
    # One statement so FK constraints don't block ordering; RESTART IDENTITY
    # resets sequences, CASCADE follows FKs to any dependent rows.
    names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    if not names:
        return
    db.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))
    db.commit()


def _clickhouse_tables(ch: ClickHouseService) -> list[tuple[str, str]]:
    rows = ch.run_query(
        "SELECT database, name FROM system.tables "
        f"WHERE match(database, '{_PER_APP_DB_PATTERN}')"
    )
    return [(r["database"], r["name"]) for r in rows]


def _clickhouse_counts(ch: ClickHouseService, tables: list[tuple[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for db_name, table in tables:
        rows = ch.run_query(f"SELECT count() AS c FROM `{db_name}`.`{table}`")
        counts[f"{db_name}.{table}"] = int(rows[0]["c"]) if rows else 0
    return counts


@router.post(
    "/cleanup",
    response_model=CleanupResponse,
    dependencies=[Depends(require_admin_key)],
)
async def cleanup(body: CleanupRequest, db: Session = Depends(get_db)):
    """Empty all Nova tables (Postgres + per-app ClickHouse). TRUNCATE only —
    the schema is preserved. Pass ``{"dry_run": true}`` to preview counts."""
    pg_counts = _postgres_counts(db)

    ch = ClickHouseService()
    ch_tables = _clickhouse_tables(ch)
    ch_counts = _clickhouse_counts(ch, ch_tables)

    if not body.dry_run:
        _truncate_postgres(db)
        for db_name, table in ch_tables:
            ch.execute(f"TRUNCATE TABLE `{db_name}`.`{table}`")
        logger.warning(
            "Admin cleanup wiped %s Postgres rows across %s tables and %s "
            "ClickHouse rows across %s tables",
            sum(pg_counts.values()), len(pg_counts),
            sum(ch_counts.values()), len(ch_counts),
        )

    return CleanupResponse(
        dry_run=body.dry_run,
        postgres=pg_counts,
        clickhouse=ch_counts,
        postgres_total=sum(pg_counts.values()),
        clickhouse_total=sum(ch_counts.values()),
    )
