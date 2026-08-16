"""Create comics, subscriptions, snapshots and download tasks."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260816_02"
down_revision: str | None = "20260816_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "comics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("remote_id", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("author", sa.String(255)),
        sa.Column("language", sa.String(32)),
        sa.Column("detail_path", sa.String(255), nullable=False),
        sa.Column("cover_url", sa.Text()),
        sa.Column("description", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_comics_remote_id", "comics", ["remote_id"], unique=True)
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("comic_id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("content_types", sa.JSON(), nullable=False),
        sa.Column("download_format", sa.String(8), nullable=False),
        sa.Column("initialization_strategy", sa.String(16), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime()),
        sa.Column("last_success_at", sa.DateTime()),
        sa.Column("next_check_at", sa.DateTime()),
        sa.Column("last_error_code", sa.String(64)),
        sa.Column("last_error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["comic_id"], ["comics.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("comic_id"),
    )
    op.create_index("ix_subscriptions_comic_id", "subscriptions", ["comic_id"], unique=True)
    op.create_table(
        "remote_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("comic_id", sa.Integer(), nullable=False),
        sa.Column("remote_id", sa.String(64), nullable=False),
        sa.Column("content_type", sa.String(16), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("sort_order", sa.Integer()),
        sa.Column("page_count", sa.Integer()),
        sa.Column("mobi_size_mb", sa.Numeric(12, 3)),
        sa.Column("epub_size_mb", sa.Numeric(12, 3)),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["comic_id"], ["comics.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("comic_id", "content_type", "remote_id", name="uq_remote_item_identity"),
    )
    op.create_index("ix_remote_items_comic_id", "remote_items", ["comic_id"])
    op.create_table(
        "download_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("remote_item_id", sa.Integer(), nullable=False),
        sa.Column("download_format", sa.String(8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("progress_bytes", sa.BigInteger(), nullable=False),
        sa.Column("total_bytes", sa.BigInteger()),
        sa.Column("temporary_path", sa.Text()),
        sa.Column("final_path", sa.Text()),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["remote_item_id"], ["remote_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("remote_item_id", "download_format", name="uq_download_task_item_format"),
    )
    op.create_index("ix_download_tasks_remote_item_id", "download_tasks", ["remote_item_id"])
    op.create_index("ix_download_tasks_status", "download_tasks", ["status"])
    op.create_table(
        "activity_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("comic_id", sa.Integer()),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["comic_id"], ["comics.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_activity_events_event_type", "activity_events", ["event_type"])
    op.create_index("ix_activity_events_comic_id", "activity_events", ["comic_id"])
    op.create_index("ix_activity_events_created_at", "activity_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("activity_events")
    op.drop_table("download_tasks")
    op.drop_table("remote_items")
    op.drop_table("subscriptions")
    op.drop_table("comics")
