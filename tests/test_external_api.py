from __future__ import annotations

import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from kmoe_subscriptions.config import Settings
from kmoe_subscriptions.kmoe.client import KmoeClient
from kmoe_subscriptions.main import create_app


ADMIN_PASSWORD = "correct horse battery staple"
API_TOKEN = "external-api-token-000000000000"
FIXTURES = Path(__file__).parent / "fixtures" / "kmoe"


class NoopDownloadService:
    def __init__(self, *args, **kwargs) -> None:
        pass

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    def wake(self) -> None:
        pass


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def kmoe_transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def connected_app(tmp_path: Path, *, api_token: str | None) -> TestClient:
    app = create_app(
        Settings(
            app_secret_key="s" * 48,
            api_token=api_token,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'external.db'}",
            download_dir=tmp_path / "downloads",
        )
    )
    app.state.download_service_factory = NoopDownloadService

    def handler(request: httpx.Request) -> httpx.Response:
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
                headers={"Set-Cookie": "session=external-cookie; Path=/"},
            )
        if path == "/my.php":
            return httpx.Response(200, request=request, text='<a href="/logout.php">out</a>')
        assert request.headers.get("cookie") == "session=external-cookie"
        if path == "/c/50076.htm":
            return httpx.Response(
                200,
                request=request,
                text=fixture_text("comic_detail_current.html"),
            )
        if path == "/data_book.php":
            return httpx.Response(
                200,
                request=request,
                json=json.loads(fixture_text("volume_data_all_types.json")),
            )
        raise AssertionError(request.url)

    app.state.kmoe_client_factory = lambda: KmoeClient(
        ("mox.moe",),
        rate_limit_delay=0,
        transport=httpx.MockTransport(handler),
    )
    return TestClient(app)


def connect_kmoe(web: TestClient) -> None:
    setup = web.post("/api/auth/setup", json={"password": ADMIN_PASSWORD})
    assert setup.status_code == 201
    csrf = setup.json()["csrf_token"]
    connected = web.post(
        "/api/kmoe/login",
        json={"email": "reader@example.com", "password": "kmoe-password"},
        headers={"X-CSRF-Token": csrf},
    )
    assert connected.status_code == 200


def auth(token: str | None = API_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def test_external_api_is_disabled_without_token(tmp_path: Path) -> None:
    with connected_app(tmp_path, api_token=None) as web:
        response = web.get("/api/v1/subscriptions")
        assert response.status_code == 403
        assert "disabled" in response.json()["detail"]


def test_external_api_requires_valid_bearer_token(tmp_path: Path) -> None:
    with connected_app(tmp_path, api_token=API_TOKEN) as web:
        assert web.get("/api/v1/subscriptions").status_code == 401
        assert web.get("/api/v1/subscriptions", headers=auth("wrong-token")).status_code == 401
        assert (
            web.get("/api/v1/subscriptions", headers={"Authorization": "Basic abc"}).status_code
            == 401
        )
        assert web.get("/api/v1/subscriptions", headers=auth()).status_code == 200


def test_external_subscription_lifecycle(tmp_path: Path) -> None:
    with connected_app(tmp_path, api_token=API_TOKEN) as web:
        connect_kmoe(web)
        headers = auth()

        assert web.get("/api/v1/subscriptions", headers=headers).json() == []

        created = web.post(
            "/api/v1/subscriptions",
            json={
                "remote_id": "50076",
                "content_types": ["volume"],
                "download_format": "epub",
                "initialization_strategy": "backfill",
            },
            headers=headers,
        )
        assert created.status_code == 201
        status = created.json()
        subscription_id = status["id"]
        assert status["title"]
        assert status["content_types"] == ["volume"]
        assert status["download_format"] == "epub"
        assert status["initialization_strategy"] == "backfill"
        assert status["enabled"] is True
        assert status["downloads"]["pending"] == 1

        # 查询订阅状况：列表与单条都返回同一状态
        listed = web.get("/api/v1/subscriptions", headers=headers)
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()] == [subscription_id]

        single = web.get(
            f"/api/v1/subscriptions/{subscription_id}", headers=headers
        )
        assert single.status_code == 200
        assert single.json() == status

        # 重复创建同一漫画返回 409
        duplicate = web.post(
            "/api/v1/subscriptions",
            json={
                "remote_id": "50076",
                "content_types": ["volume"],
                "download_format": "mobi",
                "initialization_strategy": "future_only",
            },
            headers=headers,
        )
        assert duplicate.status_code == 409

        # 删除必须明确选择是否取消等待中的任务
        assert (
            web.delete(f"/api/v1/subscriptions/{subscription_id}", headers=headers).status_code
            == 422
        )
        deleted = web.delete(
            f"/api/v1/subscriptions/{subscription_id}",
            params={"cancel_pending": "true"},
            headers=headers,
        )
        assert deleted.status_code == 204
        assert web.get("/api/v1/subscriptions", headers=headers).json() == []
        assert (
            web.get(f"/api/v1/subscriptions/{subscription_id}", headers=headers).status_code
            == 404
        )


def test_external_subscription_edit_and_check(tmp_path: Path) -> None:
    with connected_app(tmp_path, api_token=API_TOKEN) as web:
        connect_kmoe(web)
        headers = auth()

        created = web.post(
            "/api/v1/subscriptions",
            json={
                "remote_id": "50076",
                "content_types": ["volume"],
                "download_format": "epub",
                "initialization_strategy": "backfill",
            },
            headers=headers,
        )
        assert created.status_code == 201
        subscription_id = created.json()["id"]
        assert created.json()["downloads"]["pending"] == 1

        edited = web.patch(
            f"/api/v1/subscriptions/{subscription_id}",
            json={
                "content_types": ["extra", "serial"],
                "download_format": "mobi",
                "initialization_strategy": "backfill",
            },
            headers=headers,
        )
        assert edited.status_code == 200
        status = edited.json()
        assert status["content_types"] == ["extra", "serial"]
        assert status["download_format"] == "mobi"
        assert status["initialization_strategy"] == "backfill"
        assert status["reconciliation"]["created"] == 2
        assert status["downloads"]["pending"] == 3

        checked = web.post(
            f"/api/v1/subscriptions/{subscription_id}/check", headers=headers
        )
        assert checked.status_code == 202
        assert checked.json()["queued_count"] == 1
        assert checked.json()["created"] is True
        assert (
            web.post("/api/v1/subscriptions/99999/check", headers=headers).status_code
            == 404
        )
