from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base
from backend.app.iam.models import TimestampMixin


class ShellRunnerInvocation(Base, TimestampMixin):
    __tablename__ = "shell_runner_invocations"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "invocation_ref",
            name="uq_shell_runner_invocations_project_ref",
        ),
        Index(
            "ix_shell_runner_invocations_project_run_node_trace",
            "project_id",
            "run_id",
            "node_id",
            "trace_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    invocation_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    template_ref: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    template_version: Mapped[int] = mapped_column(nullable=False)
    command_hash: Mapped[str] = mapped_column(String(120), nullable=False)
    sandbox_image: Mapped[str] = mapped_column(String(260), nullable=False)
    sandbox_image_digest: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    egress_profile_ref: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    egress_proxy_mode: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    network_mode: Mapped[str] = mapped_column(String(120), nullable=False, default="none")
    workflow_ref: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    run_id: Mapped[str] = mapped_column(String(160), nullable=False, default="", index=True)
    node_id: Mapped[str] = mapped_column(String(160), nullable=False, default="", index=True)
    trace_id: Mapped[str] = mapped_column(String(160), nullable=False, default="", index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    exit_code: Mapped[int | None] = mapped_column(nullable=True)
    duration_ms: Mapped[int] = mapped_column(nullable=False, default=0)
    resource_usage: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    stdout_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    stderr_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error_type: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    updated_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
