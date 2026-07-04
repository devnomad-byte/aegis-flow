from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base
from backend.app.iam.models import TimestampMixin


class PolicyGateEvent(Base, TimestampMixin):
    __tablename__ = "policy_gate_events"
    __table_args__ = (
        UniqueConstraint("project_id", "event_ref", name="uq_policy_gate_events_project_ref"),
        Index(
            "ix_policy_gate_events_project_run_node_trace",
            "project_id",
            "run_id",
            "node_id",
            "trace_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    event_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    gate_ref: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    policy_ref: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    rule_ref: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    target_type: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    target_ref: Mapped[str] = mapped_column(String(260), nullable=False, default="")
    workflow_ref: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    run_id: Mapped[str] = mapped_column(String(160), nullable=False, default="", index=True)
    node_id: Mapped[str] = mapped_column(String(160), nullable=False, default="", index=True)
    trace_id: Mapped[str] = mapped_column(String(160), nullable=False, default="", index=True)
    decision: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    approval_required: Mapped[bool] = mapped_column(nullable=False, default=False)
    approval_task_ref: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    reason_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    duration_ms: Mapped[int] = mapped_column(nullable=False, default=0)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    updated_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
