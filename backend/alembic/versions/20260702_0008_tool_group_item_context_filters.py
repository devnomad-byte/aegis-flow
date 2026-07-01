"""add tool group item context filters

Revision ID: 20260702_0008
Revises: 20260702_0007
Create Date: 2026-07-02 00:08:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260702_0008"
down_revision: str | None = "20260702_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tool_registry_tool_group_items",
        sa.Column(
            "allowed_role_refs",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    op.add_column(
        "tool_registry_tool_group_items",
        sa.Column(
            "allowed_workflow_refs",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    op.add_column(
        "tool_registry_tool_group_items",
        sa.Column(
            "allowed_agent_refs",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    op.alter_column("tool_registry_tool_group_items", "allowed_role_refs", server_default=None)
    op.alter_column("tool_registry_tool_group_items", "allowed_workflow_refs", server_default=None)
    op.alter_column("tool_registry_tool_group_items", "allowed_agent_refs", server_default=None)


def downgrade() -> None:
    op.drop_column("tool_registry_tool_group_items", "allowed_agent_refs")
    op.drop_column("tool_registry_tool_group_items", "allowed_workflow_refs")
    op.drop_column("tool_registry_tool_group_items", "allowed_role_refs")
