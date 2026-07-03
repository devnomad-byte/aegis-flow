from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ProjectActivityKind = Literal["tool_invocation", "model_invocation"]


class ProjectCommandProjectSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: UUID
    project_slug: str
    project_name: str
    status: str


class ProjectCommandKpis(BaseModel):
    model_config = ConfigDict(frozen=True)

    workflow_drafts: int = Field(ge=0)
    mcp_servers: int = Field(ge=0)
    unhealthy_mcp_servers: int = Field(ge=0)
    pending_approvals: int = Field(ge=0)
    high_risk_invocations: int = Field(ge=0)
    recent_activity: int = Field(ge=0)


class ProjectMcpHealthItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    server_id: UUID
    server_ref: str
    name: str
    environment_key: str
    status: str
    last_health_status: str
    last_health_checked_at: datetime | None
    last_sync_status: str


class ProjectPendingApprovalItem(BaseModel):
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


class ProjectRecentActivityItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    kind: ProjectActivityKind
    label: str
    status: str
    run_id: str
    node_id: str
    trace_id: str
    risk_level: str
    duration_ms: int = Field(ge=0)
    occurred_at: datetime


class ProjectCommandCenterResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    project: ProjectCommandProjectSummary
    kpis: ProjectCommandKpis
    mcp_health: list[ProjectMcpHealthItem]
    pending_approvals: list[ProjectPendingApprovalItem]
    recent_activity: list[ProjectRecentActivityItem]
