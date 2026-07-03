from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AuditEventCreate(BaseModel):
    project_id: UUID | None = None
    actor_id: UUID
    action: str
    target_type: str
    target_id: str
    result: str = "success"
    risk_level: str = "low"
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuditEventRead(AuditEventCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime


class AuditEventListResponse(BaseModel):
    events: list[AuditEventRead]
    count: int


class AuditEventFilterInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID | None = None
    actor_id: UUID | None = None
    action: str | None = Field(default=None, max_length=120)
    risk_level: str | None = Field(default=None, max_length=32)
    result: str | None = Field(default=None, max_length=32)
    target_type: str | None = Field(default=None, max_length=80)
    created_from: datetime | None = None
    created_to: datetime | None = None


class AuditExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)
    filters: AuditEventFilterInput = Field(default_factory=AuditEventFilterInput)


class AuditExportResponse(BaseModel):
    request_id: UUID
    status: str
    event_count: int


class RawTraceAccessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)
    run_id: str = Field(min_length=1, max_length=160)
    trace_id: str = Field(min_length=1, max_length=160)
    target_type: str = Field(min_length=1, max_length=80)
    target_id: str = Field(min_length=1, max_length=160)


class RawTraceAccessResponse(BaseModel):
    request_id: UUID
    status: str
