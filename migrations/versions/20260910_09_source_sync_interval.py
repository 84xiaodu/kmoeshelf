"""Add per-source sync interval."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260910_09"
down_revision: str | None = "20260910_08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("subscription_sources") as batch:
        batch.add_column(
            sa.Column(
                "sync_interval_hours",
                sa.Integer(),
                nullable=False,
                server_default="24",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("subscription_sources") as batch:
        batch.drop_column("sync_interval_hours")
