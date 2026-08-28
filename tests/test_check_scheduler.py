from __future__ import annotations

import json
import sqlite3
import time
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


def wait_for_batch(web: TestClient, batch_id: int) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = web.get(f"/api/checks/{batch_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] in {"completed", "failed"}:
            return payload
        time.sleep(0.02)
    raise AssertionError("check batch did not finish")


def test_manual_checks_are_persistent_and_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "checks.db"
    app = create_app(
        Settings(
            app_secret_key="q" * 48,
            database_url=f"sqlite+aiosqlite:///{database_path}",
            download_dir=tmp_path / "downloads",
        )
    )
    include_new_volume = False

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
                headers={"Set-Cookie": "session=check-cookie; Path=/"},
            )
        if path == "/my.php":
            return httpx.Response(200, request=request, text='<a href="/logout.php">out</a>')
        assert request.headers.get("cookie") == "session=check-cookie"
        if path == "/c/50076.htm":
            return httpx.Response(
                200,
                request=request,
                text=fixture_text("comic_detail_current.html"),
            )
        if path == "/data_book.php":
            payload = json.loads(fixture_text("volume_data_all_types.json"))
            if include_new_volume:
                payload["voldata"].append(
                    [
                        "v102",
                        0,
                        0,
                        "單行本",
                        2,
                        "Volume 2",
                        100,
                        110,
                        "20",
                        "9",
                        "7",
                        "8",
                    ]
                )
                payload["volcount"] = 4
            return httpx.Response(200, request=request, json=payload)
        raise AssertionError(request.url)

    app.state.kmoe_client_factory = lambda: KmoeClient(
        ("mox.moe",),
        rate_limit_delay=0,
        transport=httpx.MockTransport(handler),
    )
    with TestClient(app) as web:
        setup = web.post("/api/auth/setup", json={"password": ADMIN_PASSWORD})
        csrf = setup.json()["csrf_token"]
        headers = {"X-CSRF-Token": csrf}
        assert web.post(
            "/api/kmoe/login",
            json={"email": "reader@example.com", "password": "kmoe-password"},
            headers=headers,
        ).status_code == 200
        created = web.post(
            "/api/subscriptions",
            json={
                "remote_id": "50076",
                "content_types": ["volume"],
                "download_format": "epub",
                "initialization_strategy": "future_only",
            },
            headers=headers,
        )
        subscription_id = created.json()["id"]
        assert created.json()["next_check_at"] is not None

        assert web.get("/api/settings").json() == {
            "check_interval_hours": 6,
            "download_concurrency": 2,
            "max_download_retries": 3,
            "preferred_mirror": "mox.moe",
        }
        updated = web.patch(
            "/api/settings",
            json={
                "check_interval_hours": 2,
                "download_concurrency": 3,
                "max_download_retries": 4,
                "preferred_mirror": "kxo.moe",
            },
            headers=headers,
        )
        assert updated.json() == {
            "check_interval_hours": 2,
            "download_concurrency": 3,
            "max_download_retries": 4,
            "preferred_mirror": "kxo.moe",
        }
        assert app.state.download_service.concurrency == 3

        include_new_volume = True
        first = web.post(
            f"/api/checks/subscriptions/{subscription_id}", headers=headers
        )
        assert first.status_code == 202
        first_batch = wait_for_batch(web, first.json()["batch_id"])
        assert first_batch["status"] == "completed"
        assert first_batch["completed_count"] == 1

        second = web.post(
            f"/api/checks/subscriptions/{subscription_id}", headers=headers
        )
        second_batch = wait_for_batch(web, second.json()["batch_id"])
        assert second_batch["status"] == "completed"

    with sqlite3.connect(database_path) as connection:
        cursor = connection.execute(
            "INSERT INTO check_batches "
            "(trigger, status, created_at, started_at, completed_at) "
            "VALUES ('recovery_test', 'running', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL)"
        )
        recovery_batch_id = cursor.lastrowid
        connection.execute(
            "INSERT INTO subscription_checks "
            "(batch_id, subscription_id, status, discovered_count, error_code, "
            "error_message, created_at, started_at, completed_at) "
            "VALUES (?, ?, 'running', 0, NULL, NULL, CURRENT_TIMESTAMP, "
            "CURRENT_TIMESTAMP, NULL)",
            (recovery_batch_id, subscription_id),
        )
        connection.commit()

    restarted = create_app(
        Settings(
            app_secret_key="q" * 48,
            database_url=f"sqlite+aiosqlite:///{database_path}",
            download_dir=tmp_path / "downloads",
        )
    )
    restarted.state.kmoe_client_factory = lambda: KmoeClient(
        ("mox.moe",),
        rate_limit_delay=0,
        transport=httpx.MockTransport(handler),
    )
    with TestClient(restarted) as web:
        assert web.post(
            "/api/auth/login", json={"password": ADMIN_PASSWORD}
        ).status_code == 200
        recovered = wait_for_batch(web, recovery_batch_id)
        assert recovered["status"] == "completed"

    with sqlite3.connect(database_path) as connection:
        task_count = connection.execute(
            "SELECT COUNT(*) FROM download_tasks"
        ).fetchone()[0]
        checks = connection.execute(
            "SELECT status, discovered_count FROM subscription_checks ORDER BY id"
        ).fetchall()
    assert task_count == 1
    assert checks == [("completed", 1), ("completed", 0), ("completed", 0)]
