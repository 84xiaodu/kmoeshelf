from __future__ import annotations

import asyncio
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from kmoe_subscriptions.db import Base, create_database
from kmoe_subscriptions.main import alembic_config, migrate


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
