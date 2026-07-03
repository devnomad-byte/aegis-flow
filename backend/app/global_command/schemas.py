from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

GlobalHealthStatus = Literal["healthy", "degraded", "critical", "unknown"]


class GlobalOverviewMetrics(BaseModel):
    total_projects: int = Field(ge=0)
    active_projects: int = Field(ge=0)
    active_members: int = Field(ge=0)
    total_tool_invocations: int = Field(ge=0)
    success_rate: float = Field(ge=0, le=1)
    avg_duration_ms: int = Field(ge=0)


class GlobalRiskApprovalSummary(BaseModel):
    high_risk_invocations: int = Field(ge=0)
    denied_invocations: int = Field(ge=0)
    failed_invocations: int = Field(ge=0)
    pending_approvals: int = Field(ge=0)
    expired_approvals: int = Field(ge=0)


class GlobalSystemHealthSummary(BaseModel):
    api_status: GlobalHealthStatus
    database_status: GlobalHealthStatus
    mcp_gateway_status: GlobalHealthStatus
    approval_queue_status: GlobalHealthStatus
    audit_log_status: GlobalHealthStatus
    total_mcp_servers: int = Field(ge=0)
    unhealthy_mcp_servers: int = Field(ge=0)


class GlobalAuditSummary(BaseModel):
    total_events: int = Field(ge=0)
    critical_events: int = Field(ge=0)
    high_events: int = Field(ge=0)
    recent_denied_events: int = Field(ge=0)


class GlobalCostSummary(BaseModel):
    model_cost_estimate_cents: int = Field(ge=0)
    token_count_estimate: int = Field(ge=0)
    source: Literal["not_connected", "estimated", "metered"]


class GlobalRunTrendPoint(BaseModel):
    date: str
    tool_invocations: int = Field(ge=0)
    failed_invocations: int = Field(ge=0)
    high_risk_invocations: int = Field(ge=0)
    audit_events: int = Field(ge=0)


class GlobalProjectHealthSummary(BaseModel):
    project_id: UUID
    project_slug: str
    project_name: str
    status: str
    active_members: int = Field(ge=0)
    mcp_servers: int = Field(ge=0)
    unhealthy_mcp_servers: int = Field(ge=0)
    tool_invocations: int = Field(ge=0)
    failed_invocations: int = Field(ge=0)
    high_risk_invocations: int = Field(ge=0)
    pending_approvals: int = Field(ge=0)
    recent_audit_events: int = Field(ge=0)
    risk_score: int = Field(ge=0, le=100)


class GlobalCommandCenterResponse(BaseModel):
    overview: GlobalOverviewMetrics
    risk_approval: GlobalRiskApprovalSummary
    system_health: GlobalSystemHealthSummary
    audit: GlobalAuditSummary
    cost: GlobalCostSummary
    run_trend: list[GlobalRunTrendPoint]
    projects: list[GlobalProjectHealthSummary]
