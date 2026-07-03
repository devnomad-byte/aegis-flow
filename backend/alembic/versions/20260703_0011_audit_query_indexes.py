"""add audit query indexes

Revision ID: 20260703_0011
Revises: 20260703_0010
Create Date: 2026-07-03 00:11:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260703_0011"
down_revision: str | None = "20260703_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "audit_logs",
        "project_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )
    op.create_index(op.f("ix_audit_logs_created_at"), "audit_logs", ["created_at"], unique=False)
    op.create_index(
        op.f("ix_audit_logs_project_id_created_at"),
        "audit_logs",
        ["project_id", "created_at"],
        unique=False,
    )
    op.create_index(op.f("ix_audit_logs_result"), "audit_logs", ["result"], unique=False)
    op.create_index(op.f("ix_audit_logs_risk_level"), "audit_logs", ["risk_level"], unique=False)
    op.create_index(op.f("ix_audit_logs_target_type"), "audit_logs", ["target_type"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_logs_target_type"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_risk_level"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_result"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_project_id_created_at"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_created_at"), table_name="audit_logs")
    op.alter_column(
        "audit_logs",
        "project_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
