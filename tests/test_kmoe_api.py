from __future__ import annotations

import sqlite3
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from kmoe_subscriptions.config import Settings
from kmoe_subscriptions.kmoe.client import KmoeClient
from kmoe_subscriptions.main import create_app


ADMIN_PASSWORD = "correct horse battery staple"


def test_admin_can_connect_kmoe_without_storing_password(tmp_path: Path) -> None:
    database_path = tmp_path / "api.db"
    app = create_app(
        Settings(
            app_secret_key="k" * 48,
            database_url=f"sqlite+aiosqlite:///{database_path}",
            download_dir=tmp_path / "downloads",
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login.php":
            return httpx.Response(
                200, request=request, text='<script>fetch("/login_act.php")</script>'
            )
        if request.url.path == "/login_act.php":
            return httpx.Response(
                200,
                request=request,
                json={"msgid": "m100"},
                headers={"Set-Cookie": "session=encrypted-me; Path=/"},
            )
        if request.url.path == "/my.php":
            return httpx.Response(200, request=request, text='<a href="/logout.php">out</a>')
        raise AssertionError(request.url)

    app.state.kmoe_client_factory = lambda: KmoeClient(
        ("mox.moe",),
        rate_limit_delay=0,
        transport=httpx.MockTransport(handler),
    )
    with TestClient(app) as web:
        assert web.get("/api/kmoe/status").status_code == 401
        setup = web.post("/api/auth/setup", json={"password": ADMIN_PASSWORD})
        csrf = setup.json()["csrf_token"]
        response = web.post(
            "/api/kmoe/login",
            json={"email": "reader@example.com", "password": "kmoe-password"},
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status_code == 200
        assert response.json() == {
            "connected": True,
            "email": "reader@example.com",
            "mirror": "mox.moe",
            "status": "active",
        }
        assert web.get("/api/kmoe/status").json()["connected"] is True

    with sqlite3.connect(database_path) as connection:
        encrypted = connection.execute(
            "SELECT encrypted_cookies FROM kmoe_credentials WHERE id = 1"
        ).fetchone()[0]
    assert "kmoe-password" not in encrypted
    assert "encrypted-me" not in encrypted


def test_kmoe_login_rejects_invalid_email_before_network(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            app_secret_key="k" * 48,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'api.db'}",
            download_dir=tmp_path / "downloads",
        )
    )
    with TestClient(app) as web:
        setup = web.post("/api/auth/setup", json={"password": ADMIN_PASSWORD})
        response = web.post(
            "/api/kmoe/login",
            json={"email": "not-an-email", "password": "secret"},
            headers={"X-CSRF-Token": setup.json()["csrf_token"]},
        )
    assert response.status_code == 422
