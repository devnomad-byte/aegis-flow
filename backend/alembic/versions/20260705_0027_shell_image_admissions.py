"""Add shell image admission records.

Revision ID: 20260705_0027
Revises: 20260705_0026
Create Date: 2026-07-05 13:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260705_0027"
down_revision: str | None = "20260705_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tool_registry_shell_templates",
        sa.Column(
            "image_registry_digest",
            sa.String(length=160),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "tool_registry_shell_templates",
        sa.Column("image_registry_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tool_registry_shell_templates",
        sa.Column(
            "image_signature_status",
            sa.String(length=32),
            nullable=False,
            server_default="not_checked",
        ),
    )
    op.add_column(
        "tool_registry_shell_templates",
        sa.Column(
            "image_sbom_status",
            sa.String(length=32),
            nullable=False,
            server_default="not_checked",
        ),
    )
    op.add_column(
        "tool_registry_shell_templates",
        sa.Column(
            "image_vulnerability_status",
            sa.String(length=32),
            nullable=False,
            server_default="not_checked",
        ),
    )
    op.add_column(
        "tool_registry_shell_templates",
        sa.Column(
            "image_admission_status",
            sa.String(length=32),
            nullable=False,
            server_default="not_required",
        ),
    )
    op.add_column(
        "tool_registry_shell_templates",
        sa.Column("image_admission_reason", sa.Text(), nullable=False, server_default=""),
    )
    op.create_table(
        "tool_registry_image_admissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("image_ref", sa.String(length=260), nullable=False),
        sa.Column("image_digest", sa.String(length=160), nullable=False),
        sa.Column("registry_url", sa.String(length=1024), nullable=False),
        sa.Column("registry_digest", sa.String(length=160), nullable=False),
        sa.Column("digest_match", sa.Boolean(), nullable=False),
        sa.Column(
            "signature_status",
            sa.String(length=32),
            nullable=False,
            server_default="not_checked",
        ),
        sa.Column(
            "sbom_status",
            sa.String(length=32),
            nullable=False,
            server_default="not_checked",
        ),
        sa.Column(
            "vulnerability_status",
            sa.String(length=32),
            nullable=False,
            server_default="not_checked",
        ),
        sa.Column("policy_decision", sa.String(length=32), nullable=False),
        sa.Column("decision_reason", sa.Text(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "image_ref",
            "image_digest",
            name="uq_tool_image_admission_project_ref_digest",
        ),
    )
    op.create_index(
        op.f("ix_tool_registry_image_admissions_created_by"),
        "tool_registry_image_admissions",
        ["created_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_registry_image_admissions_project_id"),
        "tool_registry_image_admissions",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_registry_image_admissions_updated_by"),
        "tool_registry_image_admissions",
        ["updated_by"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_tool_registry_image_admissions_updated_by"),
        table_name="tool_registry_image_admissions",
    )
    op.drop_index(
        op.f("ix_tool_registry_image_admissions_project_id"),
        table_name="tool_registry_image_admissions",
    )
    op.drop_index(
        op.f("ix_tool_registry_image_admissions_created_by"),
        table_name="tool_registry_image_admissions",
    )
    op.drop_table("tool_registry_image_admissions")
    op.drop_column("tool_registry_shell_templates", "image_admission_reason")
    op.drop_column("tool_registry_shell_templates", "image_admission_status")
    op.drop_column("tool_registry_shell_templates", "image_vulnerability_status")
    op.drop_column("tool_registry_shell_templates", "image_sbom_status")
    op.drop_column("tool_registry_shell_templates", "image_signature_status")
    op.drop_column("tool_registry_shell_templates", "image_registry_checked_at")
    op.drop_column("tool_registry_shell_templates", "image_registry_digest")
