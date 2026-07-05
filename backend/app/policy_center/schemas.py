from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PolicyCenterProjectSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: UUID
    project_slug: str
    project_name: str
    status: str


class PolicyCenterSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    role_count: int = Field(ge=0)
    permission_count: int = Field(ge=0)
    member_count: int = Field(ge=0)
    pending_approval_count: int = Field(ge=0)
    recent_policy_event_count: int = Field(ge=0)
    high_risk_surface_count: int = Field(ge=0)
    model_policy_count: int = Field(ge=0)
    egress_profile_count: int = Field(ge=0)
    shell_policy_status: str


class PolicyCenterRoleItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    role_id: UUID
    code: str
    name: str
    description: str
    member_count: int = Field(ge=0)
    permission_count: int = Field(ge=0)
    permission_codes: list[str]


class PolicyCenterPermissionGroup(BaseModel):
    model_config = ConfigDict(frozen=True)

    prefix: str
    count: int = Field(ge=0)
    permission_codes: list[str]


class PolicyCenterRiskSurface(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    kind: str
    label: str
    status: str
    risk_level: str
    environment_key: str = ""
    policy_ref: str = ""
    summary: str = ""
    updated_at: datetime | None = None


class PolicyCenterPendingApproval(BaseModel):
    model_config = ConfigDict(frozen=True)

    approval_task_id: UUID
    tool_ref: str
    tool_name: str
    server_ref: str
    effective_risk_level: str
    status: str
    run_id: str
    node_id: str
    trace_id: str
    tool_call_id: str
    requested_by: UUID
    expires_at: datetime
    created_at: datetime


class PolicyCenterPolicyEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: UUID
    event_ref: str
    gate_ref: str
    policy_ref: str
    rule_ref: str
    target_type: str
    target_ref: str
    workflow_ref: str
    run_id: str
    node_id: str
    trace_id: str
    decision: str
    risk_level: str
    approval_required: bool
    reason_summary: str
    duration_ms: int = Field(ge=0)
    created_at: datetime


class PolicyCenterOverviewResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    project: PolicyCenterProjectSummary
    summary: PolicyCenterSummary
    roles: list[PolicyCenterRoleItem]
    permission_groups: list[PolicyCenterPermissionGroup]
    risk_surfaces: list[PolicyCenterRiskSurface]
    pending_approvals: list[PolicyCenterPendingApproval]
    recent_policy_events: list[PolicyCenterPolicyEvent]
