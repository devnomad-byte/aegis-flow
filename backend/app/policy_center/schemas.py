from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ApprovalPolicyStatus = Literal["draft", "published", "superseded"]
ApprovalPolicyTargetKind = Literal["tool_invocation", "shell_execution", "model_invocation"]
ApprovalPolicyAction = Literal["allow", "require_approval", "deny"]
ApprovalPolicyRiskLevel = Literal["low", "medium", "high", "critical"]


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


class ApprovalPolicyRuleMatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_group_refs: list[str] = Field(default_factory=list)
    tool_refs: list[str] = Field(default_factory=list)
    shell_template_refs: list[str] = Field(default_factory=list)
    model_policy_refs: list[str] = Field(default_factory=list)
    environment_keys: list[str] = Field(default_factory=list)


class ApprovalPolicyRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=160)
    target_kind: ApprovalPolicyTargetKind
    action: ApprovalPolicyAction
    risk_levels: list[ApprovalPolicyRiskLevel] = Field(min_length=1)
    match: ApprovalPolicyRuleMatch = Field(default_factory=ApprovalPolicyRuleMatch)
    approver_role_refs: list[str] = Field(default_factory=list)
    reason: str = Field(default="", max_length=1000)


class ApprovalPolicyImpactSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    matched_surface_count: int = Field(ge=0)
    high_risk_surface_count: int = Field(ge=0)
    tool_surface_count: int = Field(ge=0)
    shell_surface_count: int = Field(ge=0)
    model_policy_count: int = Field(ge=0)
    deny_rule_count: int = Field(ge=0)
    approval_rule_count: int = Field(ge=0)


class ApprovalPolicyValidationIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    message: str
    rule_id: str = ""


class ApprovalPolicyValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    valid: bool
    blocking_issues: list[ApprovalPolicyValidationIssue]
    warnings: list[ApprovalPolicyValidationIssue]
    impact_summary: ApprovalPolicyImpactSummary


class ApprovalPolicyDraftCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_ref: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    rules: list[ApprovalPolicyRule] = Field(default_factory=list)
    source_version_id: UUID | None = None


class ApprovalPolicyRollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_version: int = Field(ge=1)
    reason: str = Field(default="", max_length=1000)


class ApprovalPolicyVersionRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    policy_ref: str
    version: int
    status: ApprovalPolicyStatus
    title: str
    description: str
    rules: list[ApprovalPolicyRule]
    rule_count: int = Field(ge=0)
    validation_result: ApprovalPolicyValidationResult | None
    impact_summary: ApprovalPolicyImpactSummary | None
    source_version_id: UUID | None
    published_at: datetime | None
    published_by: UUID | None
    created_at: datetime
    updated_at: datetime


class ApprovalPolicyVersionSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    policy_ref: str
    version: int
    status: ApprovalPolicyStatus
    title: str
    description: str
    rule_count: int = Field(ge=0)
    validation_result: ApprovalPolicyValidationResult | None
    impact_summary: ApprovalPolicyImpactSummary | None
    source_version_id: UUID | None
    published_at: datetime | None
    published_by: UUID | None
    created_at: datetime
    updated_at: datetime


class ApprovalPolicyVersionListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    current: ApprovalPolicyVersionSummary | None
    versions: list[ApprovalPolicyVersionSummary]
    count: int = Field(ge=0)
