from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from backend.app.tool_registry.schemas import RiskLevel

ToolInvocationStatus = Literal[
    "success",
    "failed",
    "denied",
    "pending_approval",
    "expired",
    "cancelled",
]
ToolInvocationPolicyDecision = Literal["allowed", "denied", "approval_required"]
ToolApprovalStatus = Literal["pending", "approved", "rejected", "revoked", "expired", "resumed"]
ToolApprovalDecisionRead = Literal["approved", "rejected", "revoked"]


class ToolInvocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_ref: str = Field(min_length=1, max_length=260)
    arguments: dict[str, Any] = Field(default_factory=dict)
    tool_group_refs: list[str] = Field(default_factory=list)
    workflow_ref: str = Field(default="", max_length=160)
    agent_ref: str = Field(default="", max_length=160)
    role_refs: list[str] = Field(default_factory=list)
    run_id: str = Field(default="", max_length=160)
    node_id: str = Field(default="", max_length=160)
    trace_id: str = Field(default="", max_length=160)
    tool_call_id: str = Field(default="", max_length=160)


class ToolGatewayResult(BaseModel):
    content: list[dict[str, Any]]
    structured_content: dict[str, Any]
    is_error: bool


class ToolInvocationCreate(BaseModel):
    project_id: UUID
    actor_id: UUID
    tool_ref: str
    tool_name: str
    server_ref: str
    tool_group_refs: list[str]
    workflow_ref: str
    agent_ref: str
    role_refs: list[str]
    run_id: str
    node_id: str
    trace_id: str
    tool_call_id: str
    effective_risk_level: RiskLevel
    approval_required: bool
    policy_decision: ToolInvocationPolicyDecision
    status: ToolInvocationStatus
    input_summary: str
    output_summary: str
    error_type: str = ""
    error_message: str = ""
    duration_ms: int = 0
    credential_ref: str = ""
    secret_lease_id: UUID | None = None
    secret_lease_ref: str = ""
    created_by: UUID
    updated_by: UUID


class ToolInvocationRead(ToolInvocationCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


class ToolInvocationResponse(BaseModel):
    invocation_id: UUID
    project_id: UUID
    tool_ref: str
    tool_name: str
    server_ref: str
    status: ToolInvocationStatus
    policy_decision: ToolInvocationPolicyDecision
    effective_risk_level: RiskLevel
    approval_required: bool
    input_summary: str
    output_summary: str
    error_type: str
    error_message: str
    duration_ms: int
    credential_ref: str
    secret_lease_ref: str
    run_id: str
    node_id: str
    trace_id: str
    tool_call_id: str
    result: ToolGatewayResult | None = None
    approval_task: "ToolApprovalTaskRead | None" = None


class ToolApprovalTaskCreate(BaseModel):
    project_id: UUID
    invocation_id: UUID
    requested_by: UUID
    tool_ref: str
    tool_name: str
    server_ref: str
    tool_group_refs: list[str]
    workflow_ref: str
    agent_ref: str
    role_refs: list[str]
    run_id: str
    node_id: str
    trace_id: str
    tool_call_id: str
    effective_risk_level: RiskLevel
    status: ToolApprovalStatus = "pending"
    decision: str = ""
    decision_reason: str = ""
    request_payload: dict[str, Any]
    authorized_tool_snapshot: dict[str, Any]
    expires_at: datetime
    created_by: UUID
    updated_by: UUID


class ToolApprovalTaskRead(ToolApprovalTaskCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    decided_by: UUID | None = None
    decided_at: datetime | None = None
    resumed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ToolApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: ToolApprovalDecisionRead
    reason: str = Field(min_length=1, max_length=500)
