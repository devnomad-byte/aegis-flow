"""add tool group item assignments

Revision ID: 20260702_0007
Revises: 20260702_0006
Create Date: 2026-07-02 00:07:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260702_0007"
down_revision: str | None = "20260702_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_registry_tool_group_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("tool_group_id", sa.Uuid(), nullable=False),
        sa.Column("tool_definition_id", sa.Uuid(), nullable=False),
        sa.Column("group_ref", sa.String(length=120), nullable=False),
        sa.Column("tool_ref", sa.String(length=260), nullable=False),
        sa.Column("server_ref", sa.String(length=120), nullable=False),
        sa.Column("tool_name", sa.String(length=160), nullable=False),
        sa.Column("display_name", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("input_schema", sa.JSON(), nullable=False),
        sa.Column("output_schema", sa.JSON(), nullable=False),
        sa.Column("annotations", sa.JSON(), nullable=False),
        sa.Column("risk_level_override", sa.String(length=32), nullable=True),
        sa.Column("effective_risk_level", sa.String(length=32), nullable=False),
        sa.Column("approval_required", sa.Boolean(), nullable=False),
        sa.Column("parameter_policy", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["tool_definition_id"], ["tool_registry_tool_definitions.id"]),
        sa.ForeignKeyConstraint(["tool_group_id"], ["tool_registry_tool_groups.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "tool_group_id",
            "tool_definition_id",
            name="uq_tool_group_item_project_group_definition",
        ),
        sa.UniqueConstraint(
            "project_id",
            "group_ref",
            "tool_ref",
            name="uq_tool_group_item_project_group_tool_ref",
        ),
    )
    op.create_index(
        op.f("ix_tool_registry_tool_group_items_created_by"),
        "tool_registry_tool_group_items",
        ["created_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_registry_tool_group_items_project_id"),
        "tool_registry_tool_group_items",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_registry_tool_group_items_tool_definition_id"),
        "tool_registry_tool_group_items",
        ["tool_definition_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_registry_tool_group_items_tool_group_id"),
        "tool_registry_tool_group_items",
        ["tool_group_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_registry_tool_group_items_updated_by"),
        "tool_registry_tool_group_items",
        ["updated_by"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_tool_registry_tool_group_items_updated_by"),
        table_name="tool_registry_tool_group_items",
    )
    op.drop_index(
        op.f("ix_tool_registry_tool_group_items_tool_group_id"),
        table_name="tool_registry_tool_group_items",
    )
    op.drop_index(
        op.f("ix_tool_registry_tool_group_items_tool_definition_id"),
        table_name="tool_registry_tool_group_items",
    )
    op.drop_index(
        op.f("ix_tool_registry_tool_group_items_project_id"),
        table_name="tool_registry_tool_group_items",
    )
    op.drop_index(
        op.f("ix_tool_registry_tool_group_items_created_by"),
        table_name="tool_registry_tool_group_items",
    )
    op.drop_table("tool_registry_tool_group_items")
