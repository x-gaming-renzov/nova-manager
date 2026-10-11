from datetime import date, datetime
from typing import Callable, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from nova_manager.api.sync.request_response import (
    SyncDigestResponse,
    SyncRowsResponse,
    SyncTablesResponse,
)
from nova_manager.components.auth.dependencies import require_app_context
from nova_manager.components.sync.export_controller import (
    SyncExportController,
    SyncMarkersMissing,
    SyncSourceUnavailable,
)
from nova_manager.components.sync.tables import SYNC_TABLES
from nova_manager.core.config import SYNC_EXPORT_MAX_LIMIT
from nova_manager.core.security import AuthContext

router = APIRouter()

_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S.%f"


def _timestamp(value: Optional[str], name: str) -> Optional[str]:
    """Timestamps travel as the exact string the export returned, so no precision is lost."""
    if value is None:
        return None
    try:
        datetime.strptime(value, _TIMESTAMP_FORMAT)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{name} must look like 2026-10-11 12:00:00.000000 (UTC)",
        )
    return value


def _known_table(table: str) -> str:
    if table not in SYNC_TABLES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown sync table: {table}")
    return table


def _export(read: Callable[[], dict]) -> dict:
    try:
        return read()
    except SyncMarkersMissing:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sync marker columns are missing; run scripts/bootstrap_clickhouse.py for this environment",
        )
    except SyncSourceUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="ClickHouse is not reachable"
        )


@router.get("/tables/", response_model=SyncTablesResponse)
async def list_sync_tables(auth: AuthContext = Depends(require_app_context)):
    controller = SyncExportController(auth.organisation_id, auth.app_id)
    return _export(controller.tables)


@router.get("/{table}/rows/", response_model=SyncRowsResponse)
async def get_sync_rows(
    table: str,
    limit: int = Query(5000, ge=1, le=SYNC_EXPORT_MAX_LIMIT),
    after_ts: Optional[str] = None,
    after_id: Optional[UUID] = None,
    day: Optional[date] = None,
    until: Optional[str] = None,
    auth: AuthContext = Depends(require_app_context),
):
    """Rows in write order, after the cursor. Pass back `next_cursor` to continue."""
    if (after_ts is None) != (after_id is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="after_ts and after_id must be given together",
        )
    after_ts = _timestamp(after_ts, "after_ts")
    until = _timestamp(until, "until")
    table = _known_table(table)

    controller = SyncExportController(auth.organisation_id, auth.app_id)
    return _export(
        lambda: controller.rows(
            table,
            limit=limit,
            after_ts=after_ts,
            after_id=str(after_id) if after_id else None,
            day=day.isoformat() if day else None,
            until=until,
        )
    )


@router.get("/{table}/digest/", response_model=SyncDigestResponse)
async def get_sync_digest(
    table: str,
    from_day: Optional[date] = Query(None, alias="from"),
    to_day: Optional[date] = Query(None, alias="to"),
    until: Optional[str] = None,
    auth: AuthContext = Depends(require_app_context),
):
    """Row count and checksum per UTC day of write time, to compare against a mirror."""
    if from_day and to_day and from_day > to_day:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="from must not be later than to"
        )
    until = _timestamp(until, "until")
    table = _known_table(table)

    controller = SyncExportController(auth.organisation_id, auth.app_id)
    return _export(
        lambda: controller.digest(
            table,
            from_day=from_day.isoformat() if from_day else None,
            to_day=to_day.isoformat() if to_day else None,
            until=until,
        )
    )
