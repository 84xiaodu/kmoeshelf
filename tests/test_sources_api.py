from __future__ import annotations

from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from kmoe_subscriptions.config import Settings
from kmoe_subscriptions.external.bangumi import BangumiClient
from kmoe_subscriptions.main import create_app


PASSWORD = "correct horse battery staple"


def test_bangumi_source_reads_wish_and_doing_collections(tmp_path: Path) -> None:
    requested_types: list[str] = []
    fail = False

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v0/users/reader/collections"
        if fail:
            return httpx.Response(503, request=request, json={"error": "temporary"})
        assert request.headers["authorization"] == "Bearer source-token"
        collection_type = request.url.params["type"]
        requested_types.append(collection_type)
        subject_id = {"1": 101, "3": 103}[collection_type]
        return httpx.Response(
            200,
            request=request,
            json={
                "data": [
                    {
                        "subject_id": subject_id,
                        "subject_type": 1,
                        "type": int(collection_type),
                        "rate": 0,
                        "tags": [],
                        "ep_status": 0,
                        "vol_status": 0,
                        "updated_at": "2026-09-10T00:00:00Z",
                        "private": False,
                        "subject": {
                            "id": subject_id,
                            "name": f"Book {subject_id}",
                            "name_cn": f"漫画 {subject_id}",
                            "score": 8.0,
                            "rank": subject_id,
                            "images": {"common": f"https://lain.test/{subject_id}.jpg"},
                        },
                    }
                ]
            },
        )

    app = create_app(
        Settings(
            app_secret_key="s" * 48,
            bangumi_access_token="source-token",
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'sources.db'}",
            download_dir=tmp_path / "downloads",
        )
    )
    app.state.bangumi_client_factory = lambda: BangumiClient(
        base_url="https://bangumi.test",
        access_token="source-token",
        transport=httpx.MockTransport(handler),
    )

    with TestClient(app) as web:
        assert web.get("/api/sources").status_code == 401
        setup = web.post("/api/auth/setup", json={"password": PASSWORD})
        csrf = setup.json()["csrf_token"]
        headers = {"X-CSRF-Token": csrf}

        created = web.post(
            "/api/sources",
            headers=headers,
            json={
                "name": "我的 Bangumi",
                "username": "reader",
                "collection_types": ["wish", "doing"],
                "enabled": True,
                "sync_interval_hours": 12,
            },
        )
        assert created.status_code == 201
        source_id = created.json()["id"]
        assert created.json()["item_count"] == 0
        assert created.json()["sync_interval_hours"] == 12

        synced = web.post(f"/api/sources/{source_id}/sync", headers=headers)
        assert synced.status_code == 200
        assert synced.json()["imported_count"] == 2
        assert synced.json()["source"]["item_count"] == 2
        assert requested_types == ["1", "3"]

        items = web.get(f"/api/sources/{source_id}/items")
        assert items.status_code == 200
        assert [(item["external_id"], item["source_status"]) for item in items.json()] == [
            ("103", "doing"),
            ("101", "wish"),
        ]
        assert items.json()[0]["external_url"] == "https://bgm.tv/subject/103"
        assert items.json()[0]["search_query"] == "漫画 103"

        listed = web.get("/api/sources")
        assert listed.json()[0]["item_count"] == 2

        fail = True
        failed = web.post(f"/api/sources/{source_id}/sync", headers=headers)
        assert failed.status_code == 502
        assert len(web.get(f"/api/sources/{source_id}/items").json()) == 2
        assert web.get("/api/sources").json()[0]["last_error_code"] == "bangumi_unavailable"

        deleted = web.delete(f"/api/sources/{source_id}", headers=headers)
        assert deleted.status_code == 204
        assert web.get("/api/sources").json() == []
