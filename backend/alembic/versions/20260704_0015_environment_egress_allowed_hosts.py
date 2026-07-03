"""Add environment egress allowlist.

Revision ID: 20260704_0015
Revises: 20260704_0014
Create Date: 2026-07-04 00:15:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260704_0015"
down_revision: str | None = "20260704_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tool_registry_environments",
        sa.Column(
            "egress_allowed_hosts",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    op.alter_column("tool_registry_environments", "egress_allowed_hosts", server_default=None)


def downgrade() -> None:
    op.drop_column("tool_registry_environments", "egress_allowed_hosts")
