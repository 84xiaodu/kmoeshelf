"""Add stable library paths and persistent download recovery fields."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260816_05"
down_revision: str | None = "20260816_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("comics") as batch:
        batch.add_column(sa.Column("library_dir", sa.String(255), nullable=True))
    with op.batch_alter_table("download_tasks") as batch:
        batch.add_column(sa.Column("next_attempt_at", sa.DateTime(), nullable=True))
        batch.add_column(
            sa.Column(
                "cancel_requested",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(sa.Column("started_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("completed_at", sa.DateTime(), nullable=True))
        batch.create_index("ix_download_tasks_next_attempt_at", ["next_attempt_at"])


def downgrade() -> None:
    with op.batch_alter_table("download_tasks") as batch:
        batch.drop_index("ix_download_tasks_next_attempt_at")
        batch.drop_column("completed_at")
        batch.drop_column("started_at")
        batch.drop_column("cancel_requested")
        batch.drop_column("next_attempt_at")
    with op.batch_alter_table("comics") as batch:
        batch.drop_column("library_dir")
