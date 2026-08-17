from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from kmoe_subscriptions.config import Settings
from kmoe_subscriptions.main import create_app


PASSWORD = "correct horse battery staple"


def test_storage_api_browses_and_runs_empty_migration(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    app = create_app(
        Settings(
            app_secret_key="a" * 48,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'api.db'}",
            download_dir=root,
        )
    )
    with TestClient(app) as web:
        setup = web.post("/api/auth/setup", json={"password": PASSWORD})
        csrf = setup.json()["csrf_token"]
        headers = {"X-CSRF-Token": csrf}

        status = web.get("/api/storage")
        assert status.status_code == 200
        assert status.json()["active_subpath"] == ""
        assert status.json()["writable"] is True

        assert web.post("/api/storage/directories", json={"path": "Manga"}).status_code == 403
        created = web.post(
            "/api/storage/directories",
            json={"path": "Manga/Kmoe"},
            headers=headers,
        )
        assert created.status_code == 200
        assert (root / "Manga/Kmoe").is_dir()

        preview = web.post(
            "/api/storage/migrations/preview",
            json={"path": "Manga/Kmoe"},
            headers=headers,
        )
        assert preview.status_code == 200
        assert preview.json()["total_files"] == 0
        started = web.post(
            "/api/storage/migrations",
            json={"path": "Manga/Kmoe"},
            headers=headers,
        )
        assert started.status_code == 201

        for _ in range(100):
            current = web.get("/api/storage/migrations/current").json()
            if current and current["phase"] == "completed":
                break
            time.sleep(0.01)
        else:
            raise AssertionError("empty storage migration did not complete")
        assert web.get("/api/storage").json()["active_subpath"] == "Manga/Kmoe"
