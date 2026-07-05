"""Add image artifact cleanup schedule lease fields.

Revision ID: 20260705_0032
Revises: 20260705_0031
Create Date: 2026-07-05 23:55:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260705_0032"
down_revision: str | None = "20260705_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tool_registry_image_artifact_cleanup_schedules",
        sa.Column("leased_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tool_registry_image_artifact_cleanup_schedules",
        sa.Column("lease_owner", sa.String(length=160), nullable=False, server_default=""),
    )
    op.add_column(
        "tool_registry_image_artifact_cleanup_schedules",
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "tool_registry_image_artifact_cleanup_schedules",
        sa.Column("last_error_type", sa.String(length=120), nullable=False, server_default=""),
    )
    op.add_column(
        "tool_registry_image_artifact_cleanup_schedules",
        sa.Column("last_error_message", sa.Text(), nullable=False, server_default=""),
    )
    op.create_index(
        "ix_tool_image_artifact_cleanup_schedules_claim",
        "tool_registry_image_artifact_cleanup_schedules",
        ["enabled", "next_run_at", "leased_until"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tool_image_artifact_cleanup_schedules_claim",
        table_name="tool_registry_image_artifact_cleanup_schedules",
    )
    op.drop_column("tool_registry_image_artifact_cleanup_schedules", "last_error_message")
    op.drop_column("tool_registry_image_artifact_cleanup_schedules", "last_error_type")
    op.drop_column("tool_registry_image_artifact_cleanup_schedules", "failure_count")
    op.drop_column("tool_registry_image_artifact_cleanup_schedules", "lease_owner")
    op.drop_column("tool_registry_image_artifact_cleanup_schedules", "leased_until")
