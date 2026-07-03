from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base
from backend.app.iam.models import TimestampMixin


class ToolGatewayInvocation(Base, TimestampMixin):
    __tablename__ = "tool_gateway_invocations"
    __table_args__ = (
        UniqueConstraint("project_id", "tool_call_id", name="uq_tool_gateway_project_call_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    tool_ref: Mapped[str] = mapped_column(String(260), nullable=False, index=True)
    tool_name: Mapped[str] = mapped_column(String(160), nullable=False)
    server_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    tool_group_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    workflow_ref: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    agent_ref: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    role_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    run_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    node_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    trace_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    tool_call_id: Mapped[str] = mapped_column(String(160), nullable=False)
    effective_risk_level: Mapped[str] = mapped_column(String(32), nullable=False)
    approval_required: Mapped[bool] = mapped_column(nullable=False, default=False)
    policy_decision: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    input_summary: Mapped[str] = mapped_column(Text, nullable=False)
    output_summary: Mapped[str] = mapped_column(Text, nullable=False)
    error_type: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    duration_ms: Mapped[int] = mapped_column(nullable=False, default=0)
    credential_ref: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    secret_lease_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tool_registry_secret_leases.id"),
        nullable=True,
        index=True,
    )
    secret_lease_ref: Mapped[str] = mapped_column(String(260), nullable=False, default="")
    created_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    updated_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class ToolGatewayApprovalTask(Base, TimestampMixin):
    __tablename__ = "tool_gateway_approval_tasks"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "invocation_id",
            name="uq_tool_gateway_approval_project_invocation",
        ),
        UniqueConstraint(
            "project_id",
            "tool_call_id",
            name="uq_tool_gateway_approval_project_call_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    invocation_id: Mapped[UUID] = mapped_column(
        ForeignKey("tool_gateway_invocations.id"),
        nullable=False,
        index=True,
    )
    requested_by: Mapped[UUID] = mapped_column(
        ForeignKey("accounts.id"),
        nullable=False,
        index=True,
    )
    decided_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("accounts.id"),
        nullable=True,
        index=True,
    )
    tool_ref: Mapped[str] = mapped_column(String(260), nullable=False, index=True)
    tool_name: Mapped[str] = mapped_column(String(160), nullable=False)
    server_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    tool_group_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    workflow_ref: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    agent_ref: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    role_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    run_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    node_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    trace_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    tool_call_id: Mapped[str] = mapped_column(String(160), nullable=False)
    effective_risk_level: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    decision: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    decision_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    request_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    authorized_tool_snapshot: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    updated_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
