"""Add policy center approval policy versions.

Revision ID: 20260706_0034
Revises: 20260705_0033
Create Date: 2026-07-06 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260706_0034"
down_revision: str | None = "20260705_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "policy_center_approval_policy_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("policy_ref", sa.String(length=120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("rules", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("validation_result", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("impact_summary", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("source_version_id", sa.Uuid(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["published_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["policy_center_approval_policy_versions.id"],
        ),
        sa.ForeignKeyConstraint(["updated_by"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "policy_ref",
            "version",
            name="uq_policy_center_approval_policy_version",
        ),
    )
    op.create_index(
        "ix_policy_center_approval_policy_current",
        "policy_center_approval_policy_versions",
        ["project_id", "policy_ref", "status", "version"],
    )
    op.create_index(
        "ix_policy_center_approval_policy_project_status",
        "policy_center_approval_policy_versions",
        ["project_id", "status"],
    )
    op.create_index(
        op.f("ix_policy_center_approval_policy_versions_created_by"),
        "policy_center_approval_policy_versions",
        ["created_by"],
    )
    op.create_index(
        op.f("ix_policy_center_approval_policy_versions_project_id"),
        "policy_center_approval_policy_versions",
        ["project_id"],
    )
    op.create_index(
        op.f("ix_policy_center_approval_policy_versions_published_by"),
        "policy_center_approval_policy_versions",
        ["published_by"],
    )
    op.create_index(
        op.f("ix_policy_center_approval_policy_versions_source_version_id"),
        "policy_center_approval_policy_versions",
        ["source_version_id"],
    )
    op.create_index(
        op.f("ix_policy_center_approval_policy_versions_status"),
        "policy_center_approval_policy_versions",
        ["status"],
    )
    op.create_index(
        op.f("ix_policy_center_approval_policy_versions_updated_by"),
        "policy_center_approval_policy_versions",
        ["updated_by"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_policy_center_approval_policy_versions_updated_by"),
        table_name="policy_center_approval_policy_versions",
    )
    op.drop_index(
        op.f("ix_policy_center_approval_policy_versions_status"),
        table_name="policy_center_approval_policy_versions",
    )
    op.drop_index(
        op.f("ix_policy_center_approval_policy_versions_source_version_id"),
        table_name="policy_center_approval_policy_versions",
    )
    op.drop_index(
        op.f("ix_policy_center_approval_policy_versions_published_by"),
        table_name="policy_center_approval_policy_versions",
    )
    op.drop_index(
        op.f("ix_policy_center_approval_policy_versions_project_id"),
        table_name="policy_center_approval_policy_versions",
    )
    op.drop_index(
        op.f("ix_policy_center_approval_policy_versions_created_by"),
        table_name="policy_center_approval_policy_versions",
    )
    op.drop_index(
        "ix_policy_center_approval_policy_project_status",
        table_name="policy_center_approval_policy_versions",
    )
    op.drop_index(
        "ix_policy_center_approval_policy_current",
        table_name="policy_center_approval_policy_versions",
    )
    op.drop_table("policy_center_approval_policy_versions")
