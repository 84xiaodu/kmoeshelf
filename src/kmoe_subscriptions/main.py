from __future__ import annotations

import asyncio
import sqlite3
import tempfile
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from sqlalchemy import make_url, text

from .api.auth import router as auth_router
from .api.checks import router as checks_router
from .api.downloads import router as downloads_router
from .api.kmoe import router as kmoe_router
from .api.settings import router as settings_router
from .api.storage import router as storage_router
from .api.subscriptions import router as subscriptions_router
from .config import Settings, get_settings
from .db import create_database
from .external.bangumi import BangumiClient
from .kmoe.catalog import SearchTargetCache
from .kmoe.client import KmoeClient
from .services.checks import CheckService
from .services.downloads import DownloadService
from .services.storage_migrations import StorageMigrationService


def alembic_config(database_url: str) -> Config:
    source_root = Path(__file__).resolve().parents[2]
    runtime_root = Path.cwd()
    project_root = (
        runtime_root
        if (runtime_root / "alembic.ini").is_file()
        and (runtime_root / "migrations").is_dir()
        else source_root
    )
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


async def migrate(database_url: str) -> None:
    await asyncio.to_thread(command.upgrade, alembic_config(database_url), "head")


def backup_sqlite_before_migrate(database_url: str) -> Path | None:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return None
    database_path = Path(url.database).expanduser().resolve()
    if not database_path.is_file() or database_path.stat().st_size == 0:
        return None

    config = alembic_config(database_url)
    expected = set(ScriptDirectory.from_config(config).get_heads())
    with sqlite3.connect(database_path) as source:
        has_version = source.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'alembic_version'"
        ).fetchone()
        current = (
            {row[0] for row in source.execute("SELECT version_num FROM alembic_version")}
            if has_version
            else set()
        )
        if current == expected:
            return None

        backup_dir = database_path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        final_path = backup_dir / f"{database_path.stem}-before-{timestamp}.db"
        with tempfile.NamedTemporaryFile(
            dir=backup_dir, prefix=".backup-", suffix=".tmp", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
        try:
            with sqlite3.connect(temporary_path) as destination:
                source.backup(destination)
                result = destination.execute("PRAGMA quick_check").fetchone()
                if result != ("ok",):
                    raise RuntimeError("SQLite backup integrity check failed")
            temporary_path.replace(final_path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
    return final_path


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        resolved.download_dir.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(backup_sqlite_before_migrate, resolved.database_url)
        await migrate(resolved.database_url)
        app.state.database = create_database(resolved.database_url)
        app.state.storage_migration_service = app.state.storage_migration_service_factory(
            app.state.database, resolved
        )
        app.state.check_service = CheckService(
            app.state.database,
            resolved,
            lambda: app.state.kmoe_client_factory(),
            lambda: app.state.download_service.wake(),
        )
        app.state.download_service = app.state.download_service_factory(
            app.state.database,
            resolved,
            lambda: app.state.kmoe_client_factory(),
            lambda: app.state.transfer_client_factory(),
        )
        try:
            await app.state.storage_migration_service.start()
            await app.state.check_service.start()
            await app.state.download_service.start()
            yield
        finally:
            await app.state.download_service.stop()
            await app.state.check_service.stop()
            await app.state.storage_migration_service.stop()
            await app.state.database.engine.dispose()

    app = FastAPI(title="Kmoe Subscriptions", version="0.2.0", lifespan=lifespan)
    app.state.settings = resolved
    app.state.search_target_cache = SearchTargetCache()
    app.state.kmoe_client_factory = KmoeClient
    app.state.bangumi_client_factory = lambda: BangumiClient(
        base_url=resolved.bangumi_api_base_url
    )
    app.state.download_service_factory = DownloadService
    app.state.storage_migration_service_factory = StorageMigrationService
    app.state.transfer_client_factory = lambda: httpx.AsyncClient(
        follow_redirects=False,
        timeout=httpx.Timeout(60),
    )
    app.include_router(auth_router)
    app.include_router(checks_router)
    app.include_router(downloads_router)
    app.include_router(kmoe_router)
    app.include_router(settings_router)
    app.include_router(storage_router)
    app.include_router(subscriptions_router)

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready(request: Request) -> dict[str, str]:
        try:
            async with request.app.state.database.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            with tempfile.NamedTemporaryFile(dir=resolved.download_dir):
                pass
        except OSError as exc:
            raise HTTPException(status_code=503, detail="Download directory not writable") from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Database not ready") from exc
        return {"status": "ok"}

    package_frontend = Path(__file__).resolve().parent / "static"
    development_frontend = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    frontend = package_frontend if package_frontend.is_dir() else development_frontend
    if frontend.is_dir():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")

    return app
