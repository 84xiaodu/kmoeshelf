"""Add structured Kmoe quota usage fields."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260910_07"
down_revision: str | None = "20260817_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


COLUMNS = (
    sa.Column("user_level", sa.Integer(), nullable=True),
    sa.Column("is_vip", sa.Boolean(), nullable=True),
    sa.Column("free_quota_total_mb", sa.Numeric(12, 3), nullable=True),
    sa.Column("free_quota_used_mb", sa.Numeric(12, 3), nullable=True),
    sa.Column("free_quota_reset_day", sa.Integer(), nullable=True),
    sa.Column("vip_quota_total_mb", sa.Numeric(12, 3), nullable=True),
    sa.Column("vip_quota_used_mb", sa.Numeric(12, 3), nullable=True),
    sa.Column("vip_quota_reset_day", sa.Integer(), nullable=True),
    sa.Column("quota_checked_at", sa.DateTime(), nullable=True),
)


def upgrade() -> None:
    with op.batch_alter_table("kmoe_credentials") as batch:
        for column in COLUMNS:
            batch.add_column(column)


def downgrade() -> None:
    with op.batch_alter_table("kmoe_credentials") as batch:
        for column in reversed(COLUMNS):
            batch.drop_column(column.name)
