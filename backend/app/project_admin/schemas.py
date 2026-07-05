from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProjectAdminProjectSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: UUID
    project_slug: str
    project_name: str
    status: str


class ProjectAdminSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    member_count: int = Field(ge=0)
    active_member_count: int = Field(ge=0)
    inactive_member_count: int = Field(ge=0)
    role_count: int = Field(ge=0)
    permission_count: int = Field(ge=0)
    permission_group_count: int = Field(ge=0)
    recent_permission_event_count: int = Field(ge=0)


class ProjectAdminMemberItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    member_id: UUID
    account_id: UUID
    display_name: str
    email: str
    status: str
    role_codes: list[str]
    role_names: list[str]
    joined_at: datetime
    updated_at: datetime


class ProjectAdminRoleItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    role_id: UUID
    code: str
    name: str
    description: str
    member_count: int = Field(ge=0)
    permission_count: int = Field(ge=0)
    permission_codes: list[str]


class ProjectAdminPermissionGroup(BaseModel):
    model_config = ConfigDict(frozen=True)

    prefix: str
    count: int = Field(ge=0)
    permission_codes: list[str]


class ProjectAdminAuditEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: UUID
    action: str
    actor_id: UUID
    target_type: str
    target_id: str
    result: str
    risk_level: str
    summary: str
    created_at: datetime


class ProjectAdminOverviewResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    project: ProjectAdminProjectSummary
    summary: ProjectAdminSummary
    members: list[ProjectAdminMemberItem]
    roles: list[ProjectAdminRoleItem]
    permission_groups: list[ProjectAdminPermissionGroup]
    recent_permission_events: list[ProjectAdminAuditEvent]
