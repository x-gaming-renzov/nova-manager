from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class SyncCursor(BaseModel):
    after_ts: str
    after_id: str


class SyncRowsResponse(BaseModel):
    rows: List[Dict[str, Any]]
    # None when the page is empty: the caller keeps the cursor it already has.
    next_cursor: Optional[SyncCursor]
    has_more: bool
    watermark: str


class SyncDigestDay(BaseModel):
    day: str
    row_count: int
    checksum: str


class SyncDigestResponse(BaseModel):
    days: List[SyncDigestDay]
    watermark: str


class SyncTableSummary(BaseModel):
    name: str
    row_count: int
    max_written_at: Optional[str]


class SyncTablesResponse(BaseModel):
    tables: List[SyncTableSummary]
    watermark: str
