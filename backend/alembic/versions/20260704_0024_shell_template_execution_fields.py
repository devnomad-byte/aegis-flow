"""Add executable fields to shell templates.

Revision ID: 20260704_0024
Revises: 20260704_0023
Create Date: 2026-07-04 21:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260704_0024"
down_revision: str | None = "20260704_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tool_registry_shell_templates",
        sa.Column("image_ref", sa.String(length=260), nullable=False, server_default=""),
    )
    op.add_column(
        "tool_registry_shell_templates",
        sa.Column("image_digest", sa.String(length=160), nullable=False, server_default=""),
    )
    op.add_column(
        "tool_registry_shell_templates",
        sa.Column("entrypoint", sa.String(length=160), nullable=False, server_default=""),
    )
    op.add_column(
        "tool_registry_shell_templates",
        sa.Column("argv_template", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "tool_registry_shell_templates",
        sa.Column("parameter_schema", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "tool_registry_shell_templates",
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="60"),
    )
    op.alter_column("tool_registry_shell_templates", "image_ref", server_default=None)
    op.alter_column("tool_registry_shell_templates", "image_digest", server_default=None)
    op.alter_column("tool_registry_shell_templates", "entrypoint", server_default=None)
    op.alter_column("tool_registry_shell_templates", "argv_template", server_default=None)
    op.alter_column("tool_registry_shell_templates", "parameter_schema", server_default=None)
    op.alter_column("tool_registry_shell_templates", "timeout_seconds", server_default=None)


def downgrade() -> None:
    op.drop_column("tool_registry_shell_templates", "timeout_seconds")
    op.drop_column("tool_registry_shell_templates", "parameter_schema")
    op.drop_column("tool_registry_shell_templates", "argv_template")
    op.drop_column("tool_registry_shell_templates", "entrypoint")
    op.drop_column("tool_registry_shell_templates", "image_digest")
    op.drop_column("tool_registry_shell_templates", "image_ref")
