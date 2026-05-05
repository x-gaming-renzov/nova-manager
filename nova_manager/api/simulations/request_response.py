import re
from typing import Optional
from uuid import UUID as UUIDType
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9_.\-]+$")


class CreateSimulationRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    description: str = Field(default="", max_length=1024)
    scenario_id: str = Field(..., min_length=1, max_length=256)
    assumptions: dict

    @field_validator("scenario_id")
    @classmethod
    def scenario_id_must_be_safe(cls, v: str) -> str:
        if not _SAFE_NAME_RE.match(v):
            raise ValueError(
                f"Only alphanumeric, underscore, hyphen, and dot allowed, got: {v!r}"
            )
        return v


class UpdateSimulationRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=256)
    description: Optional[str] = Field(None, max_length=1024)
    assumptions: Optional[dict] = None
    status: Optional[str] = None

    @field_validator("status")
    @classmethod
    def status_must_be_valid(cls, v: str | None) -> str | None:
        if v is not None and v not in {"draft", "active", "archived"}:
            raise ValueError(f"status must be draft, active, or archived, got: {v!r}")
        return v


class SimulationResponse(BaseModel):
    pid: UUIDType
    name: str
    description: str
    scenario_id: str
    status: str
    assumptions: dict
    created_at: datetime
    modified_at: datetime

    class Config:
        from_attributes = True


class SimulationRunResponse(BaseModel):
    pid: UUIDType
    status: str
    metrics_written: int
    error_message: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]

    class Config:
        from_attributes = True


class RunSimulationResponse(BaseModel):
    run: SimulationRunResponse
    metrics_written: int
