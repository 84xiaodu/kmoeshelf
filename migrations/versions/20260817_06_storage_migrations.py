"""Add active storage subpaths and persistent file migrations."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260817_06"
down_revision: str | None = "20260816_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("app_settings") as batch:
        batch.add_column(
            sa.Column(
                "download_subpath",
                sa.String(1024),
                nullable=False,
                server_default="",
            )
        )

    op.create_table(
        "storage_migrations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_subpath", sa.String(1024), nullable=False),
        sa.Column("target_subpath", sa.String(1024), nullable=False),
        sa.Column("phase", sa.String(32), nullable=False),
        sa.Column("failed_phase", sa.String(32), nullable=True),
        sa.Column("total_files", sa.Integer(), nullable=False),
        sa.Column("processed_files", sa.Integer(), nullable=False),
        sa.Column("total_bytes", sa.BigInteger(), nullable=False),
        sa.Column("processed_bytes", sa.BigInteger(), nullable=False),
        sa.Column("current_relative_path", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_storage_migrations_phase", "storage_migrations", ["phase"]
    )
    op.create_table(
        "storage_migration_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("migration_id", sa.Integer(), nullable=False),
        sa.Column("download_task_id", sa.Integer(), nullable=False),
        sa.Column("source_relative_path", sa.Text(), nullable=False),
        sa.Column("target_relative_path", sa.Text(), nullable=False),
        sa.Column("expected_size", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["download_task_id"], ["download_tasks.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["migration_id"], ["storage_migrations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "migration_id",
            "download_task_id",
            name="uq_storage_migration_task",
        ),
    )
    op.create_index(
        "ix_storage_migration_files_download_task_id",
        "storage_migration_files",
        ["download_task_id"],
    )
    op.create_index(
        "ix_storage_migration_files_migration_id",
        "storage_migration_files",
        ["migration_id"],
    )
    op.create_index(
        "ix_storage_migration_files_status",
        "storage_migration_files",
        ["status"],
    )

    op.execute(
        sa.text(
            "UPDATE download_tasks "
            "SET final_path = '/storage/' || substr(final_path, 12), "
            "temporary_path = NULL "
            "WHERE status = 'completed' AND final_path LIKE '/downloads/%'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE download_tasks SET final_path = NULL, temporary_path = NULL "
            "WHERE status != 'completed'"
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_storage_migration_files_status",
        table_name="storage_migration_files",
    )
    op.drop_index(
        "ix_storage_migration_files_migration_id",
        table_name="storage_migration_files",
    )
    op.drop_index(
        "ix_storage_migration_files_download_task_id",
        table_name="storage_migration_files",
    )
    op.drop_table("storage_migration_files")
    op.drop_index("ix_storage_migrations_phase", table_name="storage_migrations")
    op.drop_table("storage_migrations")
    with op.batch_alter_table("app_settings") as batch:
        batch.drop_column("download_subpath")
