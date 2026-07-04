from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, BigInteger, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base
from backend.app.iam.models import TimestampMixin


class RuntimeTraceSpan(Base, TimestampMixin):
    __tablename__ = "runtime_trace_spans"
    __table_args__ = (
        UniqueConstraint("project_id", "span_id", name="uq_runtime_trace_spans_project_span"),
        Index(
            "ix_runtime_trace_spans_project_run_node_trace",
            "project_id",
            "run_id",
            "node_id",
            "trace_id",
        ),
        Index(
            "ix_runtime_trace_spans_project_source",
            "project_id",
            "source_type",
            "source_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("accounts.id"),
        nullable=True,
        index=True,
    )
    trace_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String(160), nullable=False, default="", index=True)
    workflow_ref: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    node_id: Mapped[str] = mapped_column(String(160), nullable=False, default="", index=True)
    parent_span_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    span_id: Mapped[str] = mapped_column(String(160), nullable=False)
    span_name: Mapped[str] = mapped_column(String(240), nullable=False)
    span_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="internal")
    component: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    start_time_unix_nano: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    end_time_unix_nano: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    duration_ms: Mapped[int] = mapped_column(nullable=False, default=0)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    events: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    links: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    resource: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    source_type: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    source_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    created_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    updated_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
