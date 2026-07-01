"""add project tool registry catalog tables

Revision ID: 20260702_0003
Revises: 20260702_0002
Create Date: 2026-07-02 04:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260702_0003"
down_revision: str | None = "20260702_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_registry_environments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "key", name="uq_tool_env_project_key"),
    )
    op.create_index(
        op.f("ix_tool_registry_environments_created_by"),
        "tool_registry_environments",
        ["created_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_registry_environments_project_id"),
        "tool_registry_environments",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_registry_environments_updated_by"),
        "tool_registry_environments",
        ["updated_by"],
        unique=False,
    )

    op.create_table(
        "tool_registry_mcp_servers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("server_ref", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("base_url", sa.String(length=1024), nullable=False),
        sa.Column("transport", sa.String(length=32), nullable=False),
        sa.Column("environment_key", sa.String(length=80), nullable=False),
        sa.Column("owner", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "server_ref", name="uq_tool_mcp_project_ref"),
    )
    op.create_index(
        op.f("ix_tool_registry_mcp_servers_created_by"),
        "tool_registry_mcp_servers",
        ["created_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_registry_mcp_servers_project_id"),
        "tool_registry_mcp_servers",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_registry_mcp_servers_updated_by"),
        "tool_registry_mcp_servers",
        ["updated_by"],
        unique=False,
    )

    op.create_table(
        "tool_registry_tool_groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("group_ref", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("risk_level", sa.String(length=32), nullable=False),
        sa.Column("environment_key", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "group_ref", name="uq_tool_group_project_ref"),
    )
    op.create_index(
        op.f("ix_tool_registry_tool_groups_created_by"),
        "tool_registry_tool_groups",
        ["created_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_registry_tool_groups_project_id"),
        "tool_registry_tool_groups",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_registry_tool_groups_updated_by"),
        "tool_registry_tool_groups",
        ["updated_by"],
        unique=False,
    )

    op.create_table(
        "tool_registry_shell_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("template_ref", sa.String(length=120), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("risk_level", sa.String(length=32), nullable=False),
        sa.Column("environment_key", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
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
            "template_ref",
            "template_version",
            name="uq_tool_shell_project_ref_version",
        ),
    )
    op.create_index(
        op.f("ix_tool_registry_shell_templates_created_by"),
        "tool_registry_shell_templates",
        ["created_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_registry_shell_templates_project_id"),
        "tool_registry_shell_templates",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_registry_shell_templates_updated_by"),
        "tool_registry_shell_templates",
        ["updated_by"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_tool_registry_shell_templates_updated_by"),
        table_name="tool_registry_shell_templates",
    )
    op.drop_index(
        op.f("ix_tool_registry_shell_templates_project_id"),
        table_name="tool_registry_shell_templates",
    )
    op.drop_index(
        op.f("ix_tool_registry_shell_templates_created_by"),
        table_name="tool_registry_shell_templates",
    )
    op.drop_table("tool_registry_shell_templates")
    op.drop_index(
        op.f("ix_tool_registry_tool_groups_updated_by"),
        table_name="tool_registry_tool_groups",
    )
    op.drop_index(
        op.f("ix_tool_registry_tool_groups_project_id"),
        table_name="tool_registry_tool_groups",
    )
    op.drop_index(
        op.f("ix_tool_registry_tool_groups_created_by"),
        table_name="tool_registry_tool_groups",
    )
    op.drop_table("tool_registry_tool_groups")
    op.drop_index(
        op.f("ix_tool_registry_mcp_servers_updated_by"),
        table_name="tool_registry_mcp_servers",
    )
    op.drop_index(
        op.f("ix_tool_registry_mcp_servers_project_id"),
        table_name="tool_registry_mcp_servers",
    )
    op.drop_index(
        op.f("ix_tool_registry_mcp_servers_created_by"),
        table_name="tool_registry_mcp_servers",
    )
    op.drop_table("tool_registry_mcp_servers")
    op.drop_index(
        op.f("ix_tool_registry_environments_updated_by"),
        table_name="tool_registry_environments",
    )
    op.drop_index(
        op.f("ix_tool_registry_environments_project_id"),
        table_name="tool_registry_environments",
    )
    op.drop_index(
        op.f("ix_tool_registry_environments_created_by"),
        table_name="tool_registry_environments",
    )
    op.drop_table("tool_registry_environments")
