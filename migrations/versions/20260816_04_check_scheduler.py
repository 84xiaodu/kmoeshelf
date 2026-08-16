"""Create persistent settings and subscription check queue."""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op


revision: str = "20260816_04"
down_revision: str | None = "20260816_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    app_settings = op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("check_interval_hours", sa.Integer(), nullable=False),
        sa.Column("check_concurrency", sa.Integer(), nullable=False),
        sa.Column("download_concurrency", sa.Integer(), nullable=False),
        sa.Column("max_download_retries", sa.Integer(), nullable=False),
        sa.Column("preferred_mirror", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.bulk_insert(
        app_settings,
        [
            {
                "id": 1,
                "check_interval_hours": 6,
                "check_concurrency": 1,
                "download_concurrency": 2,
                "max_download_retries": 3,
                "preferred_mirror": "mox.moe",
                "updated_at": datetime.now(UTC).replace(tzinfo=None),
            }
        ],
    )
    op.create_table(
        "check_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trigger", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_check_batches_status", "check_batches", ["status"])
    op.create_table(
        "subscription_checks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("subscription_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("discovered_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["batch_id"], ["check_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["subscription_id"], ["subscriptions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "subscription_id", name="uq_batch_subscription"),
    )
    op.create_index(
        "ix_subscription_checks_batch_id", "subscription_checks", ["batch_id"]
    )
    op.create_index(
        "ix_subscription_checks_subscription_id",
        "subscription_checks",
        ["subscription_id"],
    )
    op.create_index(
        "ix_subscription_checks_status", "subscription_checks", ["status"]
    )


def downgrade() -> None:
    op.drop_index("ix_subscription_checks_status", table_name="subscription_checks")
    op.drop_index(
        "ix_subscription_checks_subscription_id", table_name="subscription_checks"
    )
    op.drop_index("ix_subscription_checks_batch_id", table_name="subscription_checks")
    op.drop_table("subscription_checks")
    op.drop_index("ix_check_batches_status", table_name="check_batches")
    op.drop_table("check_batches")
    op.drop_table("app_settings")
