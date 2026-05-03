from typing import Any, Dict, List, Literal, Optional
from uuid import UUID as UUIDType
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
import math
import re


class TrackEventRequest(BaseModel):
    user_id: str
    timestamp: datetime
    event_name: str
    event_data: dict | None


class TrackEventItem(BaseModel):
    event_name: str
    event_data: dict | None = None
    timestamp: datetime


class TrackEventsRequest(BaseModel):
    user_id: str
    events: List[TrackEventItem]


class CreateMetricRequest(BaseModel):
    name: str
    description: str
    type: Literal["count", "aggregation", "ratio", "retention", "operational", "formula"]
    config: dict


class MetricResponse(BaseModel):
    pid: UUIDType
    name: str
    description: str
    type: Literal["count", "aggregation", "ratio", "retention", "operational", "formula"]
    config: dict

    class Config:
        from_attributes = True


class TimeRange(BaseModel):
    start: str
    end: str


class ComputeMetricRequest(BaseModel):
    type: Literal["count", "aggregation", "ratio", "retention", "operational", "formula"]
    config: Dict[str, Any]


_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9_.\-]+$")


class BusinessDataItem(BaseModel):
    metric_name: str = Field(..., min_length=1, max_length=256)
    dimension: str = Field(default="", max_length=256)
    value: float
    period_start: datetime
    currency: str = Field(default="", max_length=10)

    @field_validator("metric_name", "dimension", "currency")
    @classmethod
    def must_be_safe_string(cls, v: str) -> str:
        if v and not _SAFE_NAME_RE.match(v):
            raise ValueError(
                f"Only alphanumeric, underscore, hyphen, and dot characters allowed, got: {v!r}"
            )
        return v

    @field_validator("value")
    @classmethod
    def must_be_finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError(f"value must be finite, got {v}")
        return v


class IngestBusinessDataRequest(BaseModel):
    data: List[BusinessDataItem] = Field(..., min_length=1)


class EventsSchemaResponse(BaseModel):
    pid: UUIDType
    event_name: str
    event_schema: dict

    class Config:
        from_attributes = True


class UserProfileKeyResponse(BaseModel):
    pid: UUIDType
    key: str
    type: str
    description: str

    class Config:
        from_attributes = True
