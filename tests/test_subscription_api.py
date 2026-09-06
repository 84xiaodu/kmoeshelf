from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from kmoe_subscriptions.config import Settings
from kmoe_subscriptions.kmoe.client import KmoeClient
from kmoe_subscriptions.main import create_app
from kmoe_subscriptions.api.downloads import (
    DownloadSnapshot,
    DownloadStatusCounts,
    DownloadTaskView,
    serialize_event,
)
from kmoe_subscriptions.kmoe.schemas import ContentType, DownloadFormat
from kmoe_subscriptions.models import TaskStatus


ADMIN_PASSWORD = "correct horse battery staple"
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


def test_download_event_never_exposes_temporary_or_signed_urls() -> None:
    event = serialize_event(
        DownloadSnapshot(
            tasks=[
                DownloadTaskView(
                    id=1,
                    comic_id=1,
                    comic_remote_id="50076",
                    comic_title="Comic",
                    item_remote_id="v1",
                    item_name="Volume 1",
                    content_type=ContentType.VOLUME,
                    download_format=DownloadFormat.EPUB,
                    status=TaskStatus.RUNNING,
                    attempt_count=1,
                    progress_bytes=10,
                    total_bytes=100,
                    final_path="/downloads/Comic/Volume 1.epub",
                    error_code=None,
                    error_message=None,
                    next_attempt_at=None,
                    created_at=datetime(2026, 8, 17),
                    started_at=None,
                    completed_at=None,
                )
            ],
            counts=DownloadStatusCounts(running=1),
        )
    )
    assert event.startswith("event: downloads\ndata: ")
    assert "temporary" not in event
    assert "signature" not in event


def test_download_snapshot_bounds_history_and_keeps_exact_counts(tmp_path: Path) -> None:
    database_path = tmp_path / "downloads.db"
    app = create_app(
        Settings(
            app_secret_key="s" * 48,
            database_url=f"sqlite+aiosqlite:///{database_path}",
            download_dir=tmp_path / "downloads",
        )
    )
    app.state.download_service_factory = NoopDownloadService

    with TestClient(app) as web:
        assert web.post(
            "/api/auth/setup", json={"password": ADMIN_PASSWORD}
        ).status_code == 201
        now = "2026-08-17 00:00:00"
        with sqlite3.connect(database_path) as connection:
            connection.execute(
                "INSERT INTO comics "
                "(id, remote_id, title, detail_path, created_at, updated_at) "
                "VALUES (1, 'comic-1', 'Comic', '/c/1.htm', ?, ?)",
                (now, now),
            )
            connection.executemany(
                "INSERT INTO remote_items "
                "(id, comic_id, remote_id, content_type, name, first_seen_at, last_seen_at) "
                "VALUES (?, 1, ?, 'volume', ?, ?, ?)",
                [
                    (item_id, f"item-{item_id}", f"Volume {item_id}", now, now)
                    for item_id in range(1, 212)
                ],
            )
            connection.executemany(
                "INSERT INTO download_tasks "
                "(id, remote_item_id, download_format, status, attempt_count, "
                "progress_bytes, created_at, updated_at) "
                "VALUES (?, ?, 'epub', ?, 0, 0, ?, ?)",
                [
                    (
                        task_id,
                        task_id,
                        "running"
                        if task_id == 1
                        else "failed"
                        if task_id <= 106
                        else "completed",
                        now,
                        now,
                    )
                    for task_id in range(1, 212)
                ],
            )

        response = web.get("/api/downloads")
        assert response.status_code == 200
        snapshot = response.json()
        task_ids = [task["id"] for task in snapshot["tasks"]]
        assert len(task_ids) == 101
        assert task_ids[0] == 211
        assert task_ids[-1] == 1
        assert 2 not in task_ids
        assert snapshot["counts"] == {
            "pending": 0,
            "running": 1,
            "completed": 105,
            "failed": 105,
            "cancelled": 0,
        }

        failed = web.get("/api/downloads", params={"status": "failed"})
        assert failed.status_code == 200
        failed_ids = [task["id"] for task in failed.json()["tasks"]]
        assert len(failed_ids) == 105
        assert failed_ids[-1] == 2

        completed = web.get("/api/downloads", params={"status": "completed"})
        assert completed.status_code == 200
        completed_ids = [task["id"] for task in completed.json()["tasks"]]
        assert len(completed_ids) == 100
        assert completed_ids[-1] == 112


def test_subscription_management_flow_is_transactional(tmp_path: Path) -> None:
    database_path = tmp_path / "subscriptions.db"
    app = create_app(
        Settings(
            app_secret_key="s" * 48,
            database_url=f"sqlite+aiosqlite:///{database_path}",
            download_dir=tmp_path / "downloads",
        )
    )

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
                headers={"Set-Cookie": "session=subscription-cookie; Path=/"},
            )
        if path == "/my.php":
            return httpx.Response(200, request=request, text='<a href="/logout.php">out</a>')
        assert request.headers.get("cookie") == "session=subscription-cookie"
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
    app.state.download_service_factory = NoopDownloadService
    with TestClient(app) as web:
        assert web.get("/api/downloads/events").status_code == 401
        setup = web.post("/api/auth/setup", json={"password": ADMIN_PASSWORD})
        csrf = setup.json()["csrf_token"]
        headers = {"X-CSRF-Token": csrf}
        connected = web.post(
            "/api/kmoe/login",
            json={"email": "reader@example.com", "password": "kmoe-password"},
            headers=headers,
        )
        assert connected.status_code == 200

        created = web.post(
            "/api/subscriptions",
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
        assert created.json()["content_types"] == ["volume"]
        downloads = web.get("/api/downloads", params={"status": "pending"})
        assert downloads.status_code == 200
        task_id = downloads.json()["tasks"][0]["id"]
        cancelled = web.post(f"/api/downloads/{task_id}/cancel", headers=headers)
        assert cancelled.json()["status"] == "cancelled"
        retried = web.post(f"/api/downloads/{task_id}/retry", headers=headers)
        assert retried.json()["status"] == "pending"

        duplicate = web.post(
            "/api/subscriptions",
            json={
                "remote_id": "50076",
                "content_types": ["volume"],
                "download_format": "epub",
                "initialization_strategy": "future_only",
            },
            headers=headers,
        )
        assert duplicate.status_code == 409
        assert len(web.get("/api/subscriptions").json()) == 1

        preview = web.post(
            f"/api/subscriptions/{subscription_id}/policy-preview",
            json={
                "content_types": ["extra", "serial"],
                "download_format": "mobi",
                "initialization_strategy": "backfill",
            },
            headers=headers,
        )
        assert preview.status_code == 200
        assert preview.json()["created"] == 2

        edited = web.patch(
            f"/api/subscriptions/{subscription_id}",
            json={
                "content_types": ["extra", "serial"],
                "download_format": "mobi",
                "initialization_strategy": "backfill",
            },
            headers=headers,
        )
        assert edited.status_code == 200
        assert edited.json()["content_types"] == ["extra", "serial"]
        assert edited.json()["download_format"] == "mobi"
        assert edited.json()["initialization_strategy"] == "backfill"
        assert edited.json()["reconciliation"]["created"] == 2
        assert web.post(
            f"/api/subscriptions/{subscription_id}/pause", headers=headers
        ).json()["enabled"] is False
        assert web.post(
            f"/api/subscriptions/{subscription_id}/resume", headers=headers
        ).json()["enabled"] is True

        explicit_choice = web.delete(
            f"/api/subscriptions/{subscription_id}", headers=headers
        )
        assert explicit_choice.status_code == 422
        deleted = web.delete(
            f"/api/subscriptions/{subscription_id}",
            params={"cancel_pending": "true"},
            headers=headers,
        )
        assert deleted.status_code == 204
        assert web.get("/api/subscriptions").json() == []

    with sqlite3.connect(database_path) as connection:
        tasks = connection.execute(
            "SELECT download_format, status FROM download_tasks"
        ).fetchall()
    assert tasks == [
        ("epub", "cancelled"),
        ("mobi", "cancelled"),
        ("mobi", "cancelled"),
    ]
