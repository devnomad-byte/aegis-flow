"""Add shell image admission policies.

Revision ID: 20260705_0029
Revises: 20260705_0028
Create Date: 2026-07-05 20:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260705_0029"
down_revision: str | None = "20260705_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_registry_shell_image_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column(
            "enforcement_mode",
            sa.String(length=32),
            nullable=False,
            server_default="dry_run",
        ),
        sa.Column("cosign_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notation_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notation_trust_policy", sa.JSON(), nullable=False),
        sa.Column(
            "sbom_artifact_retention_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "scan_report_retention_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "artifact_store_prefix",
            sa.String(length=240),
            nullable=False,
            server_default="shell-image-admissions",
        ),
        sa.Column(
            "artifact_retention_days",
            sa.Integer(),
            nullable=False,
            server_default="30",
        ),
        sa.Column("blocked_severities", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", name="uq_tool_shell_image_policy_project"),
    )
    op.create_index(
        op.f("ix_tool_registry_shell_image_policies_created_by"),
        "tool_registry_shell_image_policies",
        ["created_by"],
    )
    op.create_index(
        op.f("ix_tool_registry_shell_image_policies_project_id"),
        "tool_registry_shell_image_policies",
        ["project_id"],
    )
    op.create_index(
        op.f("ix_tool_registry_shell_image_policies_updated_by"),
        "tool_registry_shell_image_policies",
        ["updated_by"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_tool_registry_shell_image_policies_updated_by"),
        table_name="tool_registry_shell_image_policies",
    )
    op.drop_index(
        op.f("ix_tool_registry_shell_image_policies_project_id"),
        table_name="tool_registry_shell_image_policies",
    )
    op.drop_index(
        op.f("ix_tool_registry_shell_image_policies_created_by"),
        table_name="tool_registry_shell_image_policies",
    )
    op.drop_table("tool_registry_shell_image_policies")
