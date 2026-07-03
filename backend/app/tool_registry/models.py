from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base
from backend.app.iam.models import TimestampMixin


class ToolRegistryEnvironment(Base, TimestampMixin):
    __tablename__ = "tool_registry_environments"
    __table_args__ = (UniqueConstraint("project_id", "key", name="uq_tool_env_project_key"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    updated_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class ToolRegistryMcpServer(Base, TimestampMixin):
    __tablename__ = "tool_registry_mcp_servers"
    __table_args__ = (UniqueConstraint("project_id", "server_ref", name="uq_tool_mcp_project_ref"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    server_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    base_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    transport: Mapped[str] = mapped_column(String(32), nullable=False, default="streamable_http")
    environment_key: Mapped[str] = mapped_column(String(80), nullable=False)
    owner: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    credential_ref: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    last_health_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    last_health_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_sync_version: Mapped[int] = mapped_column(nullable=False, default=0)
    last_sync_status: Mapped[str] = mapped_column(String(32), nullable=False, default="never")
    last_sync_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    updated_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class ToolRegistryToolGroup(Base, TimestampMixin):
    __tablename__ = "tool_registry_tool_groups"
    __table_args__ = (
        UniqueConstraint("project_id", "group_ref", name="uq_tool_group_project_ref"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    group_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, default="low")
    environment_key: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    updated_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class ToolRegistryShellTemplate(Base, TimestampMixin):
    __tablename__ = "tool_registry_shell_templates"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "template_ref",
            "template_version",
            name="uq_tool_shell_project_ref_version",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    template_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    template_version: Mapped[int] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, default="low")
    environment_key: Mapped[str] = mapped_column(String(80), nullable=False)
    credential_ref: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    updated_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class ToolRegistryCredentialRef(Base, TimestampMixin):
    __tablename__ = "tool_registry_credential_refs"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "credential_ref",
            name="uq_tool_credential_ref_project_ref",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    credential_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    external_path: Mapped[str] = mapped_column(String(512), nullable=False)
    secret_kind: Mapped[str] = mapped_column(String(40), nullable=False, default="generic")
    environment_key: Mapped[str] = mapped_column(String(80), nullable=False)
    usage_scope: Mapped[str] = mapped_column(String(40), nullable=False, default="generic")
    data_classification: Mapped[str] = mapped_column(String(32), nullable=False, default="secret")
    rotation_policy: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_rotated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    owner: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    updated_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class ToolRegistryCredentialAccessIntent(Base, TimestampMixin):
    __tablename__ = "tool_registry_credential_access_intents"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    credential_ref_id: Mapped[UUID] = mapped_column(
        ForeignKey("tool_registry_credential_refs.id"),
        nullable=False,
        index=True,
    )
    credential_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    requester_type: Mapped[str] = mapped_column(String(40), nullable=False)
    requester_ref: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    run_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    node_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    trace_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    decision: Mapped[str] = mapped_column(String(32), nullable=False, default="recorded")
    denial_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    updated_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class ToolRegistrySecretLease(Base, TimestampMixin):
    __tablename__ = "tool_registry_secret_leases"
    __table_args__ = (
        UniqueConstraint("project_id", "lease_ref", name="uq_tool_secret_lease_project_ref"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    credential_ref_id: Mapped[UUID] = mapped_column(
        ForeignKey("tool_registry_credential_refs.id"),
        nullable=False,
        index=True,
    )
    credential_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    external_path: Mapped[str] = mapped_column(String(512), nullable=False)
    lease_ref: Mapped[str] = mapped_column(String(260), nullable=False)
    provider_lease_id: Mapped[str] = mapped_column(String(260), nullable=False, default="")
    requester_type: Mapped[str] = mapped_column(String(40), nullable=False)
    requester_ref: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    run_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    node_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    trace_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    ttl_seconds: Mapped[int] = mapped_column(nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    denial_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    updated_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class ToolRegistryToolDefinition(Base, TimestampMixin):
    __tablename__ = "tool_registry_tool_definitions"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "mcp_server_id",
            "tool_name",
            name="uq_tool_definition_project_server_name",
        ),
        UniqueConstraint("project_id", "tool_ref", name="uq_tool_definition_project_ref"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    mcp_server_id: Mapped[UUID] = mapped_column(
        ForeignKey("tool_registry_mcp_servers.id"),
        nullable=False,
        index=True,
    )
    server_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    tool_ref: Mapped[str] = mapped_column(String(260), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(160), nullable=False)
    display_name: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    annotations: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, default="medium")
    schema_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    sync_version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    updated_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class ToolRegistryToolGroupItem(Base, TimestampMixin):
    __tablename__ = "tool_registry_tool_group_items"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "tool_group_id",
            "tool_definition_id",
            name="uq_tool_group_item_project_group_definition",
        ),
        UniqueConstraint(
            "project_id",
            "group_ref",
            "tool_ref",
            name="uq_tool_group_item_project_group_tool_ref",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    tool_group_id: Mapped[UUID] = mapped_column(
        ForeignKey("tool_registry_tool_groups.id"),
        nullable=False,
        index=True,
    )
    tool_definition_id: Mapped[UUID] = mapped_column(
        ForeignKey("tool_registry_tool_definitions.id"),
        nullable=False,
        index=True,
    )
    group_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    tool_ref: Mapped[str] = mapped_column(String(260), nullable=False)
    server_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(160), nullable=False)
    display_name: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    annotations: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    risk_level_override: Mapped[str | None] = mapped_column(String(32), nullable=True)
    effective_risk_level: Mapped[str] = mapped_column(String(32), nullable=False, default="medium")
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    parameter_policy: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    allowed_role_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    allowed_workflow_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    allowed_agent_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    updated_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class ToolRegistryToolSyncRun(Base, TimestampMixin):
    __tablename__ = "tool_registry_tool_sync_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    mcp_server_id: Mapped[UUID] = mapped_column(
        ForeignKey("tool_registry_mcp_servers.id"),
        nullable=False,
        index=True,
    )
    server_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    sync_version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    tool_count: Mapped[int] = mapped_column(nullable=False, default=0)
    error_type: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    updated_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
