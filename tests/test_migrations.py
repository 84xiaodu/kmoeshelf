from __future__ import annotations

import asyncio
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from kmoe_subscriptions.db import Base, create_database
from kmoe_subscriptions.main import migrate


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
