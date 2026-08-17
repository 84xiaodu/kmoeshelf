from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from kmoe_subscriptions.config import Settings
from kmoe_subscriptions.db import create_database
from kmoe_subscriptions.main import migrate
from kmoe_subscriptions.models import (
    AppSetting,
    Comic,
    DownloadTask,
    RemoteItemRecord,
    StorageMigrationPhase,
    TaskStatus,
)
from kmoe_subscriptions.services.storage_migrations import (
    StorageMigrationConflict,
    StorageMigrationService,
)


async def completed_task(database, root: Path) -> Path:
    source = root / "old" / "Comic [1]" / "volumes" / "Volume [v1].epub"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"valid-epub")
    async with database.sessions.begin() as session:
        setting = await session.get(AppSetting, 1)
        assert setting is not None
        setting.download_subpath = "old"
        comic = Comic(
            remote_id="1",
            title="Comic",
            detail_path="/c/1.htm",
            library_dir="Comic [1]",
        )
        session.add(comic)
        await session.flush()
        item = RemoteItemRecord(
            comic_id=comic.id,
            remote_id="v1",
            content_type="volume",
            name="Volume",
        )
        session.add(item)
        await session.flush()
        session.add(
            DownloadTask(
                remote_item_id=item.id,
                download_format="epub",
                status=TaskStatus.COMPLETED.value,
                progress_bytes=source.stat().st_size,
                total_bytes=source.stat().st_size,
                final_path=str(source),
            )
        )
    return source


def test_migration_copies_commits_and_cleans_managed_files(tmp_path: Path) -> None:
    async def run() -> None:
        root = tmp_path / "storage"
        root.mkdir()
        settings = Settings(
            app_secret_key="m" * 48,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}",
            download_dir=root,
        )
        await migrate(settings.database_url)
        database = create_database(settings.database_url)
        source = await completed_task(database, root)
        service = StorageMigrationService(database, settings)
        preview = await service.preview("new/library")
        assert preview.total_files == 1
        assert preview.total_bytes == len(b"valid-epub")

        await service.start()
        migration = await service.create("new/library")
        for _ in range(300):
            current = await service.current()
            if current and current.phase == StorageMigrationPhase.COMPLETED.value:
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("storage migration did not complete")
        await service.stop()

        target = (
            root
            / "new/library"
            / "Comic [1]"
            / "volumes"
            / "Volume [v1].epub"
        )
        assert target.read_bytes() == b"valid-epub"
        assert not source.exists()
        async with database.sessions() as session:
            setting = await session.get(AppSetting, 1)
            task = await session.get(DownloadTask, 1)
            assert setting is not None and setting.download_subpath == "new/library"
            assert task is not None and task.final_path == str(target.resolve())
        assert migration.id == 1
        await database.engine.dispose()

    asyncio.run(run())


def test_migration_preview_rejects_different_size_target(tmp_path: Path) -> None:
    async def run() -> None:
        root = tmp_path / "storage"
        root.mkdir()
        settings = Settings(
            app_secret_key="m" * 48,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'conflict.db'}",
            download_dir=root,
        )
        await migrate(settings.database_url)
        database = create_database(settings.database_url)
        await completed_task(database, root)
        conflict = (
            root / "new" / "Comic [1]" / "volumes" / "Volume [v1].epub"
        )
        conflict.parent.mkdir(parents=True)
        conflict.write_bytes(b"different-size")
        service = StorageMigrationService(database, settings)

        with pytest.raises(StorageMigrationConflict):
            await service.preview("new")

        await database.engine.dispose()

    asyncio.run(run())
