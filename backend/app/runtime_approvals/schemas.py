from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

RuntimeApprovalTargetKind = Literal["shell_execution", "model_invocation"]
RuntimeApprovalStatus = Literal["pending", "approved", "rejected", "revoked", "expired", "resumed"]
RuntimeApprovalDecisionRead = Literal["approved", "rejected", "revoked"]


class RuntimeApprovalTaskCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: UUID
    actor_id: UUID
    target_kind: RuntimeApprovalTargetKind
    target_ref: str = Field(min_length=1, max_length=160)
    invocation_ref: str = Field(min_length=1, max_length=160)
    workflow_ref: str = Field(default="", max_length=160)
    run_id: str = Field(default="", max_length=160)
    node_id: str = Field(default="", max_length=160)
    trace_id: str = Field(default="", max_length=160)
    risk_level: str = Field(default="medium", max_length=32)
    status: RuntimeApprovalStatus = "pending"
    decision: str = Field(default="", max_length=32)
    decision_reason: str = Field(default="", max_length=500)
    request_payload: dict[str, Any] = Field(default_factory=dict)
    public_payload: dict[str, Any] = Field(default_factory=dict)
    target_snapshot: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime = Field(default_factory=lambda: datetime.now(UTC) + timedelta(minutes=30))
    created_by: UUID
    updated_by: UUID


class RuntimeApprovalTaskRead(RuntimeApprovalTaskCreate):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    decided_by: UUID | None = None
    decided_at: datetime | None = None
    resumed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class RuntimeApprovalTaskPublicRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    project_id: UUID
    actor_id: UUID
    target_kind: RuntimeApprovalTargetKind
    target_ref: str
    invocation_ref: str
    workflow_ref: str = ""
    run_id: str = ""
    node_id: str = ""
    trace_id: str = ""
    risk_level: str = "medium"
    status: RuntimeApprovalStatus = "pending"
    decision: str = ""
    decision_reason: str = ""
    public_payload: dict[str, Any] = Field(default_factory=dict)
    target_snapshot: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime
    decided_by: UUID | None = None
    decided_at: datetime | None = None
    resumed_at: datetime | None = None
    created_by: UUID
    updated_by: UUID
    created_at: datetime
    updated_at: datetime


class RuntimeApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: RuntimeApprovalDecisionRead
    reason: str = Field(min_length=1, max_length=500)


class RuntimeApprovalTaskListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    tasks: list[RuntimeApprovalTaskPublicRead]
    count: int
