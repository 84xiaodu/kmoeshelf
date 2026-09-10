"""Add generic subscription sources and normalized source items."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260910_08"
down_revision: str | None = "20260910_07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "subscription_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_code", sa.String(64), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_type", "name", name="uq_subscription_source_name"),
    )
    op.create_index(
        "ix_subscription_sources_source_type",
        "subscription_sources",
        ["source_type"],
    )
    op.create_table(
        "subscription_source_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("original_title", sa.String(255), nullable=True),
        sa.Column("source_status", sa.String(32), nullable=False),
        sa.Column("cover_url", sa.Text(), nullable=True),
        sa.Column("external_url", sa.Text(), nullable=False),
        sa.Column("search_query", sa.String(255), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"], ["subscription_sources.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "external_id", name="uq_source_item_identity"),
    )
    op.create_index(
        "ix_subscription_source_items_source_id",
        "subscription_source_items",
        ["source_id"],
    )
    op.create_index(
        "ix_subscription_source_items_source_status",
        "subscription_source_items",
        ["source_status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_subscription_source_items_source_status",
        table_name="subscription_source_items",
    )
    op.drop_index(
        "ix_subscription_source_items_source_id",
        table_name="subscription_source_items",
    )
    op.drop_table("subscription_source_items")
    op.drop_index(
        "ix_subscription_sources_source_type",
        table_name="subscription_sources",
    )
    op.drop_table("subscription_sources")
