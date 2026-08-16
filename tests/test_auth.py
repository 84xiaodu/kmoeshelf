from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from kmoe_subscriptions.config import Settings
from kmoe_subscriptions.main import create_app


PASSWORD = "correct horse battery staple"


def client(tmp_path: Path) -> TestClient:
    settings = Settings(
        app_secret_key="t" * 48,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        download_dir=tmp_path / "downloads",
    )
    return TestClient(create_app(settings))


def test_setup_login_logout(tmp_path: Path) -> None:
    with client(tmp_path) as web:
        assert web.get("/health/live").json() == {"status": "ok"}
        assert web.get("/health/ready").status_code == 200
        assert web.get("/api/auth/status").json() == {
            "setup_required": True,
            "authenticated": False,
        }

        setup = web.post("/api/auth/setup", json={"password": PASSWORD})
        assert setup.status_code == 201
        csrf = setup.json()["csrf_token"]
        assert web.get("/api/auth/me").status_code == 200
        assert web.post("/api/auth/setup", json={"password": PASSWORD}).status_code == 409

        rejected = web.post("/api/auth/logout")
        assert rejected.status_code == 403
        logout = web.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
        assert logout.status_code == 204
        assert web.get("/api/auth/me").status_code == 401

        assert web.post("/api/auth/login", json={"password": "wrong password!"}).status_code == 401
        login = web.post("/api/auth/login", json={"password": PASSWORD})
        assert login.status_code == 200
        assert web.get("/api/auth/status").json() == {
            "setup_required": False,
            "authenticated": True,
        }


def test_rejects_cross_site_setup(tmp_path: Path) -> None:
    with client(tmp_path) as web:
        response = web.post(
            "/api/auth/setup",
            json={"password": PASSWORD},
            headers={"Origin": "https://attacker.example"},
        )
        assert response.status_code == 403

