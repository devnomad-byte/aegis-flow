"""Add environment egress proxy controls.

Revision ID: 20260704_0016
Revises: 20260704_0015
Create Date: 2026-07-04 02:45:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260704_0016"
down_revision: str | None = "20260704_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tool_registry_environments",
        sa.Column(
            "egress_allowed_ports",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    op.add_column(
        "tool_registry_environments",
        sa.Column(
            "egress_proxy_mode",
            sa.String(length=32),
            nullable=False,
            server_default="direct",
        ),
    )
    op.add_column(
        "tool_registry_environments",
        sa.Column(
            "egress_proxy_url",
            sa.String(length=512),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "tool_registry_environments",
        sa.Column(
            "egress_proxy_network",
            sa.String(length=120),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "tool_registry_environments",
        sa.Column(
            "egress_dns_pinning_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.alter_column("tool_registry_environments", "egress_allowed_ports", server_default=None)
    op.alter_column("tool_registry_environments", "egress_proxy_mode", server_default=None)
    op.alter_column("tool_registry_environments", "egress_proxy_url", server_default=None)
    op.alter_column("tool_registry_environments", "egress_proxy_network", server_default=None)
    op.alter_column(
        "tool_registry_environments",
        "egress_dns_pinning_required",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("tool_registry_environments", "egress_dns_pinning_required")
    op.drop_column("tool_registry_environments", "egress_proxy_network")
    op.drop_column("tool_registry_environments", "egress_proxy_url")
    op.drop_column("tool_registry_environments", "egress_proxy_mode")
    op.drop_column("tool_registry_environments", "egress_allowed_ports")
