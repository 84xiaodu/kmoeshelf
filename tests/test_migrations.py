from __future__ import annotations

import asyncio
import sqlite3
import tempfile
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from kmoe_subscriptions.db import Base, create_database
from kmoe_subscriptions.main import (
    alembic_config,
    backup_sqlite_before_migrate,
    migrate,
)


def test_migrations_match_models(tmp_path: Path) -> None:
    async def run() -> None:
        url = f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}"
        await migrate(url)
        database = create_database(url)
        async with database.engine.connect() as connection:
            differences = await connection.run_sync(
                lambda sync_connection: compare_metadata(
                    MigrationContext.configure(sync_connection), Base.metadata
                )
            )
        await database.engine.dispose()
        assert differences == []

    asyncio.run(run())


def test_alembic_config_supports_installed_runtime_layout(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")
    (tmp_path / "migrations").mkdir()
    monkeypatch.chdir(tmp_path)

    config = alembic_config("sqlite+aiosqlite:///runtime.db")

    assert config.config_file_name == str(tmp_path / "alembic.ini")
    assert config.get_main_option("script_location") == str(tmp_path / "migrations")


def test_pending_sqlite_migration_creates_verified_backup() -> None:
    with tempfile.TemporaryDirectory(dir="/tmp") as directory:
        root = Path(directory)
        database_path = root / "app.db"
        url = f"sqlite+aiosqlite:///{database_path}"
        asyncio.run(migrate(url))
        assert backup_sqlite_before_migrate(url) is None

        with sqlite3.connect(database_path) as connection:
            connection.execute(
                "UPDATE alembic_version SET version_num = ?", ("20260816_04",)
            )
            connection.commit()

        backup = backup_sqlite_before_migrate(url)

        assert backup is not None
        assert backup.parent == root / "backups"
        with sqlite3.connect(f"file:{backup}?mode=ro", uri=True) as connection:
            assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
            assert connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone() == ("20260816_04",)
