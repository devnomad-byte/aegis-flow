from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base
from backend.app.iam.models import TimestampMixin


class WorkflowRun(Base, TimestampMixin):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        UniqueConstraint("project_id", "run_id", name="uq_workflow_runs_project_run_id"),
        Index(
            "ix_workflow_runs_project_workflow_created",
            "project_id",
            "workflow_id",
            "created_at",
        ),
        Index("ix_workflow_runs_project_trace", "project_id", "trace_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    workflow_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflow_versions.id"),
        nullable=False,
        index=True,
    )
    workflow_id: Mapped[str] = mapped_column(String(120), nullable=False)
    workflow_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    definition_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    run_id: Mapped[str] = mapped_column(String(160), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    inputs_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    outputs_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error_type: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    pending_approval: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    updated_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class WorkflowRunCheckpoint(Base, TimestampMixin):
    __tablename__ = "workflow_run_checkpoints"
    __table_args__ = (
        Index(
            "ix_workflow_run_checkpoints_project_run_created",
            "project_id",
            "run_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    workflow_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workflow_runs.id"),
        nullable=True,
        index=True,
    )
    workflow_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflow_versions.id"),
        nullable=False,
        index=True,
    )
    workflow_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    run_id: Mapped[str] = mapped_column(String(160), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(160), nullable=False)
    node_id: Mapped[str] = mapped_column(String(120), nullable=False)
    node_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    output: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error_type: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    updated_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class WorkflowRunEvent(Base, TimestampMixin):
    __tablename__ = "workflow_run_events"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "run_id",
            "sequence",
            name="uq_workflow_run_events_project_run_sequence",
        ),
        Index(
            "ix_workflow_run_events_project_run_sequence",
            "project_id",
            "run_id",
            "sequence",
        ),
        Index(
            "ix_workflow_run_events_project_trace_created",
            "project_id",
            "trace_id",
            "created_at",
        ),
        Index(
            "ix_workflow_run_events_project_version_created",
            "project_id",
            "workflow_version_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    workflow_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workflow_runs.id"),
        nullable=True,
        index=True,
    )
    workflow_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflow_versions.id"),
        nullable=False,
        index=True,
    )
    workflow_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    run_id: Mapped[str] = mapped_column(String(160), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(160), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    node_id: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    node_type: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    updated_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class WorkflowRunQueueItem(Base, TimestampMixin):
    __tablename__ = "workflow_run_queue_items"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "run_id",
            name="uq_workflow_run_queue_items_project_run_id",
        ),
        Index(
            "ix_workflow_run_queue_items_claim",
            "status",
            "available_at",
            "created_at",
        ),
        Index(
            "ix_workflow_run_queue_items_project_status",
            "project_id",
            "status",
            "updated_at",
        ),
        Index(
            "ix_workflow_run_queue_items_lease",
            "status",
            "leased_until",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    workflow_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflow_runs.id"),
        nullable=False,
        index=True,
    )
    workflow_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflow_versions.id"),
        nullable=False,
        index=True,
    )
    workflow_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    run_id: Mapped[str] = mapped_column(String(160), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    encrypted_inputs: Mapped[str] = mapped_column(Text, nullable=False)
    encryption_key_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    input_keys: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    leased_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_owner: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    last_error_type: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    last_error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    dead_letter_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    updated_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
