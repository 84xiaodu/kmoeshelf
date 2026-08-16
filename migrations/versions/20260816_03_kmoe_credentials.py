"""Create encrypted Kmoe credential storage."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260816_03"
down_revision: str | None = "20260816_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kmoe_credentials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("encrypted_cookies", sa.Text(), nullable=False),
        sa.Column("active_mirror", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("last_validated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("kmoe_credentials")

