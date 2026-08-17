from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select, update

from ..config import Settings
from ..db import Database
from ..models import (
    AppSetting,
    DownloadTask,
    StorageMigration,
    StorageMigrationFile,
    StorageMigrationFileStatus,
    StorageMigrationPhase,
    TaskStatus,
)
from ..security import utcnow
from ..storage import (
    InvalidStoragePath,
    StorageBoundary,
    StorageError,
    StoragePathSymlink,
)


ACTIVE_MIGRATION_PHASES = (
    StorageMigrationPhase.PENDING.value,
    StorageMigrationPhase.WAITING_FOR_DOWNLOADS.value,
    StorageMigrationPhase.COPYING.value,
    StorageMigrationPhase.COMMITTING.value,
    StorageMigrationPhase.CLEANING.value,
)


class StorageMigrationConflict(StorageError):
    code = "storage_target_conflict"


class StorageMigrationSourceMissing(StorageError):
    code = "storage_source_missing"


@dataclass(frozen=True, slots=True)
class StoragePreview:
    source_subpath: str
    target_subpath: str
    total_files: int
    total_bytes: int


class StorageMigrationService:
    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings
        self.boundary = StorageBoundary(settings.download_dir)
        self._wake = asyncio.Event()
        self._worker_task: asyncio.Task[None] | None = None
        self._stopping = False

    async def start(self) -> None:
        self._worker_task = asyncio.create_task(
            self._worker(), name="storage-migration-worker"
        )
        self._wake.set()

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        if self._worker_task is not None:
            await self._worker_task

    def wake(self) -> None:
        self._wake.set()

    async def current(self) -> StorageMigration | None:
        async with self.database.sessions() as session:
            return await session.scalar(
                select(StorageMigration).order_by(StorageMigration.id.desc()).limit(1)
            )

    async def active_subpath(self) -> str:
        async with self.database.sessions.begin() as session:
            setting = await self._setting(session)
            return setting.download_subpath

    async def preview(self, target_subpath: str) -> StoragePreview:
        target = self.boundary.normalize_subpath(target_subpath)
        self.boundary.assert_writable(target)
        async with self.database.sessions.begin() as session:
            setting = await self._setting(session)
            source = setting.download_subpath
            if source == target:
                raise InvalidStoragePath("Storage target is already active")
            tasks = list(
                await session.scalars(
                    select(DownloadTask).where(
                        DownloadTask.status == TaskStatus.COMPLETED.value,
                        DownloadTask.final_path.is_not(None),
                    )
                )
            )
        total_bytes = 0
        for task in tasks:
            _, size = self._planned_file(source, target, task)
            total_bytes += size
        return StoragePreview(source, target, len(tasks), total_bytes)

    async def create(self, target_subpath: str) -> StorageMigration:
        target = self.boundary.normalize_subpath(target_subpath)
        self.boundary.assert_writable(target)
        async with self.database.sessions.begin() as session:
            existing = await session.scalar(
                select(StorageMigration.id)
                .where(StorageMigration.phase != StorageMigrationPhase.COMPLETED.value)
                .limit(1)
            )
            if existing is not None:
                raise StorageMigrationConflict(
                    "A storage migration must complete before another can start"
                )
            setting = await self._setting(session)
            if setting.download_subpath == target:
                raise InvalidStoragePath("Storage target is already active")
            migration = StorageMigration(
                source_subpath=setting.download_subpath,
                target_subpath=target,
                phase=StorageMigrationPhase.PENDING.value,
            )
            session.add(migration)
            await session.flush()
        self._wake.set()
        return migration

    async def retry(self, migration_id: int) -> StorageMigration:
        async with self.database.sessions.begin() as session:
            migration = await session.get(StorageMigration, migration_id)
            if migration is None:
                raise InvalidStoragePath("Storage migration does not exist")
            if migration.phase != StorageMigrationPhase.FAILED.value:
                raise StorageMigrationConflict("Storage migration is not failed")
            migration.phase = (
                migration.failed_phase or StorageMigrationPhase.PENDING.value
            )
            if migration.phase == StorageMigrationPhase.COPYING.value:
                migration.phase = StorageMigrationPhase.WAITING_FOR_DOWNLOADS.value
            migration.failed_phase = None
            migration.error_code = None
            migration.error_message = None
            migration.completed_at = None
        self._wake.set()
        return migration

    async def _worker(self) -> None:
        while True:
            if self._stopping:
                return
            migration_id = await self._next_active_id()
            if migration_id is not None:
                try:
                    await self._advance(migration_id)
                except StorageError as exc:
                    await self._fail(migration_id, exc)
                except OSError as exc:
                    await self._fail(
                        migration_id,
                        StorageError(f"Storage operation failed with errno {exc.errno}"),
                    )
                except Exception as exc:
                    await self._fail(
                        migration_id,
                        StorageError(
                            f"Storage migration failed with {type(exc).__name__}"
                        ),
                    )
                continue
            if self._stopping:
                return
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=1)
            except TimeoutError:
                pass
            self._wake.clear()

    async def _next_active_id(self) -> int | None:
        async with self.database.sessions() as session:
            return await session.scalar(
                select(StorageMigration.id)
                .where(StorageMigration.phase.in_(ACTIVE_MIGRATION_PHASES))
                .order_by(StorageMigration.id)
                .limit(1)
            )

    async def _advance(self, migration_id: int) -> None:
        async with self.database.sessions() as session:
            migration = await session.get(StorageMigration, migration_id)
            if migration is None:
                return
            phase = migration.phase
        if phase == StorageMigrationPhase.PENDING.value:
            await self._set_phase(
                migration_id, StorageMigrationPhase.WAITING_FOR_DOWNLOADS
            )
        elif phase == StorageMigrationPhase.WAITING_FOR_DOWNLOADS.value:
            await self._wait_and_plan(migration_id)
        elif phase == StorageMigrationPhase.COPYING.value:
            await self._copy_next(migration_id)
        elif phase == StorageMigrationPhase.COMMITTING.value:
            await self._commit(migration_id)
        elif phase == StorageMigrationPhase.CLEANING.value:
            await self._clean_next(migration_id)

    async def _wait_and_plan(self, migration_id: int) -> None:
        async with self.database.sessions() as session:
            running = await session.scalar(
                select(func.count())
                .select_from(DownloadTask)
                .where(DownloadTask.status == TaskStatus.RUNNING.value)
            )
        if running:
            await asyncio.sleep(0.2)
            return
        async with self.database.sessions.begin() as session:
            migration = await session.get(StorageMigration, migration_id)
            assert migration is not None
            if migration.started_at is None:
                migration.started_at = utcnow()
            existing_task_ids = set(
                await session.scalars(
                    select(StorageMigrationFile.download_task_id).where(
                        StorageMigrationFile.migration_id == migration_id
                    )
                )
            )
            tasks = list(
                await session.scalars(
                    select(DownloadTask).where(
                        DownloadTask.status == TaskStatus.COMPLETED.value,
                        DownloadTask.final_path.is_not(None),
                    )
                )
            )
            for task in tasks:
                if task.id in existing_task_ids:
                    continue
                relative, size = self._planned_file(
                    migration.source_subpath, migration.target_subpath, task
                )
                session.add(
                    StorageMigrationFile(
                        migration_id=migration_id,
                        download_task_id=task.id,
                        source_relative_path=relative,
                        target_relative_path=relative,
                        expected_size=size,
                    )
                )
            await session.flush()
            totals = (
                await session.execute(
                    select(
                        func.count(StorageMigrationFile.id),
                        func.coalesce(func.sum(StorageMigrationFile.expected_size), 0),
                    ).where(StorageMigrationFile.migration_id == migration_id)
                )
            ).one()
            migration.total_files = int(totals[0])
            migration.total_bytes = int(totals[1])
            migration.phase = StorageMigrationPhase.COPYING.value

    def _planned_file(
        self,
        source_subpath: str,
        target_subpath: str,
        task: DownloadTask,
    ) -> tuple[str, int]:
        if not task.final_path:
            raise StorageMigrationSourceMissing(
                f"Completed download task {task.id} has no file path"
            )
        source_root = self.boundary.directory(source_subpath)
        path = Path(task.final_path)
        if path.is_symlink():
            raise StoragePathSymlink(
                f"Completed download task {task.id} points to a symbolic link"
            )
        resolved = path.resolve()
        if not resolved.is_relative_to(source_root) or not resolved.is_file():
            raise StorageMigrationSourceMissing(
                f"Completed download task {task.id} source file is missing"
            )
        relative = resolved.relative_to(source_root).as_posix()
        size = resolved.stat().st_size
        expected = task.total_bytes or size
        if size <= 0 or size != expected:
            raise StorageMigrationSourceMissing(
                f"Completed download task {task.id} source size is invalid"
            )
        target = self.boundary.managed_path(target_subpath, relative)
        if target.exists() and target.stat().st_size != size:
            raise StorageMigrationConflict(
                f"Target file conflicts for download task {task.id}"
            )
        return relative, size

    async def _copy_next(self, migration_id: int) -> None:
        async with self.database.sessions() as session:
            migration = await session.get(StorageMigration, migration_id)
            assert migration is not None
            row = await session.scalar(
                select(StorageMigrationFile)
                .where(
                    StorageMigrationFile.migration_id == migration_id,
                    StorageMigrationFile.status
                    == StorageMigrationFileStatus.PENDING.value,
                )
                .order_by(StorageMigrationFile.id)
                .limit(1)
            )
        if row is None:
            await self._set_phase(migration_id, StorageMigrationPhase.COMMITTING)
            return
        source = self.boundary.managed_path(
            migration.source_subpath, row.source_relative_path
        )
        target = self.boundary.managed_path(
            migration.target_subpath, row.target_relative_path
        )
        if not source.is_file() or source.is_symlink():
            raise StorageMigrationSourceMissing(
                f"Source file disappeared for download task {row.download_task_id}"
            )
        if target.exists():
            if target.is_symlink() or target.stat().st_size != row.expected_size:
                raise StorageMigrationConflict(
                    f"Target file conflicts for download task {row.download_task_id}"
                )
        else:
            await asyncio.to_thread(
                self._copy_verified,
                source,
                target,
                row.expected_size,
                row.id,
            )
        async with self.database.sessions.begin() as session:
            persisted = await session.get(StorageMigrationFile, row.id)
            current = await session.get(StorageMigration, migration_id)
            assert persisted is not None and current is not None
            persisted.status = StorageMigrationFileStatus.COPIED.value
            current.processed_files += 1
            current.processed_bytes += row.expected_size
            current.current_relative_path = row.target_relative_path

    @staticmethod
    def _copy_verified(
        source: Path, target: Path, expected_size: int, row_id: int
    ) -> None:
        staged = target.with_name(f".{target.name}.{row_id}.migrating")
        if staged.exists() or staged.is_symlink():
            staged.unlink()
        with source.open("rb") as input_file, staged.open("xb") as output_file:
            shutil.copyfileobj(input_file, output_file, 1024 * 1024)
            output_file.flush()
            os.fsync(output_file.fileno())
        if staged.stat().st_size != expected_size:
            staged.unlink(missing_ok=True)
            raise StorageMigrationSourceMissing("Copied file size does not match source")
        try:
            os.link(staged, target, follow_symlinks=False)
        except FileExistsError:
            if target.is_symlink() or target.stat().st_size != expected_size:
                raise StorageMigrationConflict("Target file appeared during migration")
        finally:
            staged.unlink(missing_ok=True)

    async def _commit(self, migration_id: int) -> None:
        async with self.database.sessions.begin() as session:
            migration = await session.get(StorageMigration, migration_id)
            assert migration is not None
            pending = await session.scalar(
                select(func.count())
                .select_from(StorageMigrationFile)
                .where(
                    StorageMigrationFile.migration_id == migration_id,
                    StorageMigrationFile.status
                    != StorageMigrationFileStatus.COPIED.value,
                )
            )
            if pending:
                raise StorageMigrationSourceMissing(
                    "Storage migration commit has incomplete files"
                )
            rows = list(
                await session.scalars(
                    select(StorageMigrationFile).where(
                        StorageMigrationFile.migration_id == migration_id
                    )
                )
            )
            for row in rows:
                task = await session.get(DownloadTask, row.download_task_id)
                if task is None or task.status != TaskStatus.COMPLETED.value:
                    raise StorageMigrationSourceMissing(
                        f"Download task {row.download_task_id} changed during migration"
                    )
                target = self.boundary.managed_path(
                    migration.target_subpath, row.target_relative_path
                )
                if not target.is_file() or target.stat().st_size != row.expected_size:
                    raise StorageMigrationSourceMissing(
                        f"Target file is missing for download task {row.download_task_id}"
                    )
                task.final_path = str(target)
                task.temporary_path = None
                row.status = StorageMigrationFileStatus.COMMITTED.value
            await session.execute(
                update(DownloadTask)
                .where(DownloadTask.status != TaskStatus.COMPLETED.value)
                .values(final_path=None, temporary_path=None)
            )
            setting = await self._setting(session)
            if setting.download_subpath != migration.source_subpath:
                raise StorageMigrationConflict(
                    "Active storage directory changed during migration"
                )
            setting.download_subpath = migration.target_subpath
            migration.phase = StorageMigrationPhase.CLEANING.value
            migration.current_relative_path = None

    async def _clean_next(self, migration_id: int) -> None:
        async with self.database.sessions() as session:
            migration = await session.get(StorageMigration, migration_id)
            assert migration is not None
            row = await session.scalar(
                select(StorageMigrationFile)
                .where(
                    StorageMigrationFile.migration_id == migration_id,
                    StorageMigrationFile.status
                    == StorageMigrationFileStatus.COMMITTED.value,
                )
                .order_by(StorageMigrationFile.id)
                .limit(1)
            )
        if row is None:
            async with self.database.sessions.begin() as session:
                current = await session.get(StorageMigration, migration_id)
                assert current is not None
                current.phase = StorageMigrationPhase.COMPLETED.value
                current.completed_at = utcnow()
                current.current_relative_path = None
            return
        source_root = self.boundary.directory(migration.source_subpath)
        source = self.boundary.managed_path(
            migration.source_subpath, row.source_relative_path
        )
        target = self.boundary.managed_path(
            migration.target_subpath, row.target_relative_path
        )
        if not target.is_file() or target.stat().st_size != row.expected_size:
            raise StorageMigrationSourceMissing(
                f"Committed target is missing for download task {row.download_task_id}"
            )
        if source != target:
            source.unlink(missing_ok=True)
            self._remove_empty_parents(source.parent, source_root)
        async with self.database.sessions.begin() as session:
            persisted = await session.get(StorageMigrationFile, row.id)
            current = await session.get(StorageMigration, migration_id)
            assert persisted is not None and current is not None
            persisted.status = StorageMigrationFileStatus.CLEANED.value
            current.current_relative_path = row.source_relative_path

    @staticmethod
    def _remove_empty_parents(directory: Path, stop: Path) -> None:
        while directory != stop and directory.is_relative_to(stop):
            try:
                directory.rmdir()
            except OSError:
                return
            directory = directory.parent

    async def _set_phase(
        self, migration_id: int, phase: StorageMigrationPhase
    ) -> None:
        async with self.database.sessions.begin() as session:
            migration = await session.get(StorageMigration, migration_id)
            if migration is not None:
                migration.phase = phase.value

    async def _fail(self, migration_id: int, error: StorageError) -> None:
        async with self.database.sessions.begin() as session:
            migration = await session.get(StorageMigration, migration_id)
            if migration is None:
                return
            migration.failed_phase = migration.phase
            migration.phase = StorageMigrationPhase.FAILED.value
            migration.error_code = getattr(error, "code", "storage_error")
            migration.error_message = str(error)
            migration.completed_at = utcnow()

    @staticmethod
    async def _setting(session) -> AppSetting:
        setting = await session.get(AppSetting, 1)
        if setting is None:
            setting = AppSetting(id=1)
            session.add(setting)
            await session.flush()
        return setting
