"""Add immutable workflow versions.

Revision ID: 20260704_0022
Revises: 20260704_0021
Create Date: 2026-07-04 14:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260704_0022"
down_revision: str | None = "20260704_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("analysis", sa.JSON(), nullable=False),
        sa.Column("gate_result", sa.JSON(), nullable=False),
        sa.Column("definition_hash", sa.String(length=96), nullable=False),
        sa.Column("release_note", sa.Text(), nullable=False),
        sa.Column("published_by", sa.Uuid(), nullable=False),
        sa.Column("archived_by", sa.Uuid(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["archived_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["published_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "definition_hash",
            name="uq_workflow_versions_project_definition_hash",
        ),
        sa.UniqueConstraint(
            "project_id",
            "workflow_id",
            "version",
            name="uq_workflow_versions_project_workflow_version",
        ),
    )
    op.create_index(
        op.f("ix_workflow_versions_archived_by"),
        "workflow_versions",
        ["archived_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflow_versions_created_by"),
        "workflow_versions",
        ["created_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflow_versions_project_id"),
        "workflow_versions",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_workflow_versions_project_workflow_created",
        "workflow_versions",
        ["project_id", "workflow_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflow_versions_published_by"),
        "workflow_versions",
        ["published_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflow_versions_status"),
        "workflow_versions",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflow_versions_updated_by"),
        "workflow_versions",
        ["updated_by"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_workflow_versions_updated_by"), table_name="workflow_versions")
    op.drop_index(op.f("ix_workflow_versions_status"), table_name="workflow_versions")
    op.drop_index(op.f("ix_workflow_versions_published_by"), table_name="workflow_versions")
    op.drop_index(
        "ix_workflow_versions_project_workflow_created",
        table_name="workflow_versions",
    )
    op.drop_index(op.f("ix_workflow_versions_project_id"), table_name="workflow_versions")
    op.drop_index(op.f("ix_workflow_versions_created_by"), table_name="workflow_versions")
    op.drop_index(op.f("ix_workflow_versions_archived_by"), table_name="workflow_versions")
    op.drop_table("workflow_versions")
