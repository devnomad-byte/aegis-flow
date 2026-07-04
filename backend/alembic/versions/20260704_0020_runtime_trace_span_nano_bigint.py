"""use bigint for runtime trace span nanosecond timestamps

Revision ID: 20260704_0020
Revises: 20260704_0019
Create Date: 2026-07-04 00:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260704_0020"
down_revision: str | None = "20260704_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "runtime_trace_spans",
        "start_time_unix_nano",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )
    op.alter_column(
        "runtime_trace_spans",
        "end_time_unix_nano",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "runtime_trace_spans",
        "end_time_unix_nano",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
    )
    op.alter_column(
        "runtime_trace_spans",
        "start_time_unix_nano",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
    )
