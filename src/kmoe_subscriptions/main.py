from __future__ import annotations

import asyncio
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import text

from .api.auth import router as auth_router
from .api.checks import router as checks_router
from .api.kmoe import router as kmoe_router
from .api.settings import router as settings_router
from .api.subscriptions import router as subscriptions_router
from .config import Settings, get_settings
from .db import create_database
from .kmoe.client import KmoeClient
from .services.checks import CheckService


def alembic_config(database_url: str) -> Config:
    project_root = Path(__file__).resolve().parents[2]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


async def migrate(database_url: str) -> None:
    await asyncio.to_thread(command.upgrade, alembic_config(database_url), "head")


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        resolved.download_dir.mkdir(parents=True, exist_ok=True)
        await migrate(resolved.database_url)
        app.state.database = create_database(resolved.database_url)
        app.state.check_service = CheckService(
            app.state.database,
            resolved,
            lambda: app.state.kmoe_client_factory(),
        )
        try:
            await app.state.check_service.start()
            yield
        finally:
            await app.state.check_service.stop()
            await app.state.database.engine.dispose()

    app = FastAPI(title="Kmoe Subscriptions", version="0.1.0", lifespan=lifespan)
    app.state.settings = resolved
    app.state.kmoe_client_factory = KmoeClient
    app.include_router(auth_router)
    app.include_router(checks_router)
    app.include_router(kmoe_router)
    app.include_router(settings_router)
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

    return app
