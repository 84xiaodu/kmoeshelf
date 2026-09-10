from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from kmoe_subscriptions.config import Settings
from kmoe_subscriptions.external.bangumi import BangumiClient
from kmoe_subscriptions.main import create_app
from kmoe_subscriptions.models import SubscriptionSource
from kmoe_subscriptions.security import utcnow
from kmoe_subscriptions.services.source_sync import SourceSyncService, is_due


PASSWORD = "correct horse battery staple"


def test_is_due_respects_sync_interval() -> None:
    source = SubscriptionSource(
        source_type="bangumi",
        name="source",
        config={"username": "reader", "collection_types": ["wish"]},
        sync_interval_hours=24,
    )
    assert is_due(source) is True  # never synced
    source.last_success_at = utcnow()
    assert is_due(source) is False
    source.last_success_at = utcnow() - timedelta(hours=25)
    assert is_due(source) is True


def test_source_sync_service_syncs_only_due_sources(tmp_path: Path) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={
                "data": [
                    {
                        "subject_id": 101,
                        "subject_type": 1,
                        "type": 1,
                        "rate": 0,
                        "tags": [],
                        "ep_status": 0,
                        "vol_status": 0,
                        "updated_at": "2026-09-10T00:00:00Z",
                        "private": False,
                        "subject": {
                            "id": 101,
                            "name": "Book 101",
                            "name_cn": "漫画 101",
                            "score": 8.0,
                            "rank": 101,
                        },
                    }
                ]
            },
        )

    app = create_app(
        Settings(
            app_secret_key="s" * 48,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'sync.db'}",
            download_dir=tmp_path / "downloads",
        )
    )

    def client_factory():
        nonlocal calls
        calls += 1
        return BangumiClient(
            base_url="https://bangumi.test",
            transport=httpx.MockTransport(handler),
        )

    app.state.bangumi_client_factory = client_factory
    with TestClient(app) as web:
        web.post("/api/auth/setup", json={"password": PASSWORD})
        csrf = web.post("/api/auth/login", json={"password": PASSWORD}).json()["csrf_token"]
        headers = {"X-CSRF-Token": csrf}
        created = web.post(
            "/api/sources",
            headers=headers,
            json={
                "name": "source",
                "username": "reader",
                "collection_types": ["wish"],
                "enabled": True,
                "sync_interval_hours": 24,
            },
        )
        source_id = created.json()["id"]
        web.post(f"/api/sources/{source_id}/sync", headers=headers)
        assert calls == 1

        service = SourceSyncService(
            app.state.database,
            app.state.settings,
            client_factory,
        )

        import asyncio

        # Freshly synced: not due, so no new remote call.
        asyncio.run(service.sync_due_sources())
        assert calls == 1

        async def age_source() -> None:
            async with app.state.database.sessions.begin() as session:
                source = await session.get(SubscriptionSource, source_id)
                source.last_success_at = utcnow() - timedelta(hours=25)

        asyncio.run(age_source())
        asyncio.run(service.sync_due_sources())
        assert calls == 2
