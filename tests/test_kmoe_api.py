from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from kmoe_subscriptions.config import Settings
from kmoe_subscriptions.kmoe.client import KmoeClient
from kmoe_subscriptions.main import create_app


ADMIN_PASSWORD = "correct horse battery staple"
FIXTURES = Path(__file__).parent / "fixtures" / "kmoe"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def fixture_json(name: str):
    return json.loads(fixture_text(name))


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


def test_admin_searches_and_reads_details_with_saved_cookie(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            app_secret_key="k" * 48,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'api.db'}",
            download_dir=tmp_path / "downloads",
        )
    )
    volume_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal volume_calls
        path = request.url.path
        if path == "/login.php":
            return httpx.Response(
                200, request=request, text='<script>fetch("/login_act.php")</script>'
            )
        if path == "/login_act.php":
            return httpx.Response(
                200,
                request=request,
                json={"msgid": "m100"},
                headers={"Set-Cookie": "session=saved-cookie; Path=/"},
            )
        if path == "/my.php":
            return httpx.Response(200, request=request, text='<a href="/logout.php">out</a>')
        assert request.headers.get("cookie") == "session=saved-cookie"
        if path.startswith("/l/"):
            return httpx.Response(
                200,
                request=request,
                text=fixture_text("search_results_current.html"),
            )
        if path == "/c/50076.htm":
            return httpx.Response(
                200,
                request=request,
                text=fixture_text("comic_detail_current.html"),
            )
        if path == "/data_book.php":
            assert request.url.params["h"] == "opaque_test_hash"
            volume_calls += 1
            fixture = (
                "volume_data_all_types.json"
                if volume_calls == 1
                else "volume_data_unauthenticated_empty.json"
            )
            return httpx.Response(200, request=request, json=fixture_json(fixture))
        raise AssertionError(request.url)

    app.state.kmoe_client_factory = lambda: KmoeClient(
        ("mox.moe",),
        rate_limit_delay=0,
        transport=httpx.MockTransport(handler),
    )
    with TestClient(app) as web:
        setup = web.post("/api/auth/setup", json={"password": ADMIN_PASSWORD})
        connected = web.post(
            "/api/kmoe/login",
            json={"email": "reader@example.com", "password": "kmoe-password"},
            headers={"X-CSRF-Token": setup.json()["csrf_token"]},
        )
        assert connected.status_code == 200

        search = web.get("/api/kmoe/search", params={"q": "示例", "page": 1})
        assert search.status_code == 200
        assert search.json()["results"][0]["remote_id"] == "50076"

        details = web.get("/api/kmoe/comics/50076")
        assert details.status_code == 200
        assert details.json()["description"] == "第一行第二行 & 安全"
        assert [item["content_type"] for item in details.json()["items"]] == [
            "volume",
            "extra",
            "serial",
        ]

        expired = web.get("/api/kmoe/comics/50076")
        assert expired.status_code == 401
        assert expired.json()["detail"]["code"] == "auth_expired"
        status = web.get("/api/kmoe/status")
        assert status.json()["connected"] is False
        assert status.json()["status"] == "expired"
