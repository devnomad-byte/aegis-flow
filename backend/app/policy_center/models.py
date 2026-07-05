from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base
from backend.app.iam.models import TimestampMixin


class ApprovalPolicyVersion(Base, TimestampMixin):
    __tablename__ = "policy_center_approval_policy_versions"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "policy_ref",
            "version",
            name="uq_policy_center_approval_policy_version",
        ),
        Index(
            "ix_policy_center_approval_policy_current",
            "project_id",
            "policy_ref",
            "status",
            "version",
        ),
        Index(
            "ix_policy_center_approval_policy_project_status",
            "project_id",
            "status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    policy_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rules: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    validation_result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    impact_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    source_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("policy_center_approval_policy_versions.id"),
        nullable=True,
        index=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("accounts.id"),
        nullable=True,
        index=True,
    )
    created_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    updated_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
