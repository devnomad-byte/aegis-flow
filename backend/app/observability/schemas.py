from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

RuntimeSpanKind = Literal["internal", "server", "client", "producer", "consumer", "model", "tool"]
RuntimeSpanStatus = Literal["success", "failed", "denied", "pending", "cancelled", "error"]


class RuntimeTraceSpanCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: UUID
    actor_id: UUID | None = None
    trace_id: str = Field(min_length=1, max_length=160)
    run_id: str = Field(default="", max_length=160)
    workflow_ref: str = Field(default="", max_length=160)
    node_id: str = Field(default="", max_length=160)
    parent_span_id: str = Field(default="", max_length=160)
    span_id: str = Field(min_length=1, max_length=160)
    span_name: str = Field(min_length=1, max_length=240)
    span_kind: RuntimeSpanKind = "internal"
    component: str = Field(min_length=1, max_length=80)
    status: RuntimeSpanStatus = "success"
    start_time_unix_nano: int = Field(ge=0)
    end_time_unix_nano: int = Field(ge=0)
    duration_ms: int = Field(default=0, ge=0)
    attributes: dict[str, Any] = Field(default_factory=dict)
    events: list[dict[str, Any]] = Field(default_factory=list)
    links: list[dict[str, Any]] = Field(default_factory=list)
    resource: dict[str, Any] = Field(default_factory=dict)
    source_type: str = Field(default="", max_length=120)
    source_id: str = Field(default="", max_length=160)
    created_by: UUID
    updated_by: UUID


class RuntimeTraceSpanRead(RuntimeTraceSpanCreate):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


class RuntimeTraceSpanListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    spans: list[RuntimeTraceSpanRead]
    count: int


class RuntimeTraceSpanOtlpExportResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    payload: dict[str, Any]
    span_count: int
