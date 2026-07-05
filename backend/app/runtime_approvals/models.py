from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base
from backend.app.iam.models import TimestampMixin


class RuntimeApprovalTask(Base, TimestampMixin):
    __tablename__ = "runtime_approval_tasks"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "invocation_ref",
            "target_kind",
            name="uq_runtime_approval_tasks_project_invocation_target",
        ),
        Index(
            "ix_runtime_approval_tasks_project_status_created",
            "project_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_runtime_approval_tasks_project_run_node_trace",
            "project_id",
            "run_id",
            "node_id",
            "trace_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    target_kind: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    target_ref: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    invocation_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    workflow_ref: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    run_id: Mapped[str] = mapped_column(String(160), nullable=False, default="", index=True)
    node_id: Mapped[str] = mapped_column(String(160), nullable=False, default="", index=True)
    trace_id: Mapped[str] = mapped_column(String(160), nullable=False, default="", index=True)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, default="medium")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    decision: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    decision_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    public_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    target_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_by: Mapped[UUID | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    updated_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
