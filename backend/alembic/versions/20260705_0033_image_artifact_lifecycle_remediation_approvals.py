"""Add image artifact lifecycle remediation approvals.

Revision ID: 20260705_0033
Revises: 20260705_0032
Create Date: 2026-07-05 23:59:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260705_0033"
down_revision: str | None = "20260705_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_registry_image_artifact_lifecycle_remediation_approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("rule_id", sa.String(length=160), nullable=False),
        sa.Column("prefixes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("proposal_type", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("decision_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["decided_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["requested_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_tool_registry_image_artifact_lifecycle_remediation_approvals_created_by"),
        "tool_registry_image_artifact_lifecycle_remediation_approvals",
        ["created_by"],
    )
    op.create_index(
        op.f("ix_tool_registry_image_artifact_lifecycle_remediation_approvals_decided_by"),
        "tool_registry_image_artifact_lifecycle_remediation_approvals",
        ["decided_by"],
    )
    op.create_index(
        op.f("ix_tool_registry_image_artifact_lifecycle_remediation_approvals_project_id"),
        "tool_registry_image_artifact_lifecycle_remediation_approvals",
        ["project_id"],
    )
    op.create_index(
        "ix_tool_img_lifecycle_approvals_project_status",
        "tool_registry_image_artifact_lifecycle_remediation_approvals",
        ["project_id", "status"],
    )
    op.create_index(
        op.f("ix_tool_registry_image_artifact_lifecycle_remediation_approvals_requested_by"),
        "tool_registry_image_artifact_lifecycle_remediation_approvals",
        ["requested_by"],
    )
    op.create_index(
        op.f("ix_tool_registry_image_artifact_lifecycle_remediation_approvals_updated_by"),
        "tool_registry_image_artifact_lifecycle_remediation_approvals",
        ["updated_by"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_tool_registry_image_artifact_lifecycle_remediation_approvals_updated_by"),
        table_name="tool_registry_image_artifact_lifecycle_remediation_approvals",
    )
    op.drop_index(
        op.f("ix_tool_registry_image_artifact_lifecycle_remediation_approvals_requested_by"),
        table_name="tool_registry_image_artifact_lifecycle_remediation_approvals",
    )
    op.drop_index(
        "ix_tool_img_lifecycle_approvals_project_status",
        table_name="tool_registry_image_artifact_lifecycle_remediation_approvals",
    )
    op.drop_index(
        op.f("ix_tool_registry_image_artifact_lifecycle_remediation_approvals_project_id"),
        table_name="tool_registry_image_artifact_lifecycle_remediation_approvals",
    )
    op.drop_index(
        op.f("ix_tool_registry_image_artifact_lifecycle_remediation_approvals_decided_by"),
        table_name="tool_registry_image_artifact_lifecycle_remediation_approvals",
    )
    op.drop_index(
        op.f("ix_tool_registry_image_artifact_lifecycle_remediation_approvals_created_by"),
        table_name="tool_registry_image_artifact_lifecycle_remediation_approvals",
    )
    op.drop_table("tool_registry_image_artifact_lifecycle_remediation_approvals")
