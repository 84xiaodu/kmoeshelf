from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from kmoe_subscriptions.config import Settings
from kmoe_subscriptions.db import create_database
from kmoe_subscriptions.kmoe.client import KmoeClient
from kmoe_subscriptions.kmoe.credentials import encrypt_cookies
from kmoe_subscriptions.kmoe.schemas import (
    ComicDetails,
    ContentType,
    DownloadFormat,
    RemoteItem,
)
from kmoe_subscriptions.main import migrate
from kmoe_subscriptions.models import (
    DownloadTask,
    InitializationStrategy,
    KmoeCredential,
    TaskStatus,
)
from kmoe_subscriptions.services.downloads import DownloadService
from kmoe_subscriptions.services.subscriptions import initialize_subscription
from kmoe_subscriptions.storage import download_paths


def test_worker_resumes_and_atomically_completes_download(tmp_path: Path) -> None:
    async def run() -> None:
        settings = Settings(
            app_secret_key="d" * 48,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'worker.db'}",
            download_dir=tmp_path / "downloads",
        )
        await migrate(settings.database_url)
        database = create_database(settings.database_url)
        details = ComicDetails(
            remote_id="50076",
            title="Worker comic",
            detail_path="/c/50076.htm",
            items=(
                RemoteItem(
                    remote_id="v101",
                    content_type=ContentType.VOLUME,
                    name="Volume 1",
                ),
                RemoteItem(
                    remote_id="v102",
                    content_type=ContentType.VOLUME,
                    name="Volume 2",
                ),
            ),
        )
        async with database.sessions.begin() as session:
            await initialize_subscription(
                session,
                details,
                content_types={ContentType.VOLUME},
                download_format=DownloadFormat.EPUB,
                strategy=InitializationStrategy.BACKFILL,
            )
            session.add(
                KmoeCredential(
                    id=1,
                    email="reader@example.com",
                    encrypted_cookies=encrypt_cookies(
                        settings,
                        mirror="mox.moe",
                        cookies={"session": "worker-cookie"},
                    ),
                    active_mirror="mox.moe",
                    status="active",
                )
            )
            task = await session.get(DownloadTask, 1)
            assert task is not None
            task.status = TaskStatus.RUNNING.value
            cancelled = await session.get(DownloadTask, 2)
            assert cancelled is not None
            cancelled.status = TaskStatus.RUNNING.value
            cancelled.cancel_requested = True
        paths = download_paths(
            settings.download_dir,
            library_dir="Worker comic [50076]",
            content_type=ContentType.VOLUME,
            item_name="Volume 1",
            item_id="v101",
            download_format=DownloadFormat.EPUB,
        )
        paths.temporary.parent.mkdir(parents=True)
        paths.temporary.write_bytes(b"abc")

        def kmoe_handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/getdownurl.php"
            assert request.headers.get("cookie") == "session=worker-cookie"
            return httpx.Response(
                200,
                request=request,
                json={
                    "code": 200,
                    "url": "https://cdn.example.invalid/files/book.epub?sig=fake",
                },
            )

        def transfer_handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["range"] == "bytes=3-"
            return httpx.Response(
                206,
                request=request,
                content=b"def",
                headers={
                    "Content-Range": "bytes 3-5/6",
                    "Content-Length": "3",
                    "Content-Type": "application/epub+zip",
                },
            )

        service = DownloadService(
            database,
            settings,
            lambda: KmoeClient(
                ("mox.moe",),
                rate_limit_delay=0,
                transport=httpx.MockTransport(kmoe_handler),
            ),
            lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(transfer_handler),
                follow_redirects=False,
            ),
        )
        await service.start()
        for _ in range(200):
            async with database.sessions() as session:
                task = await session.get(DownloadTask, 1)
                if task and task.status == TaskStatus.COMPLETED.value:
                    break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("download did not complete")
        await service.stop()
        async with database.sessions() as session:
            task = await session.get(DownloadTask, 1)
            assert task is not None
            assert task.progress_bytes == 6
            assert task.total_bytes == 6
            assert task.attempt_count == 1
            assert task.temporary_path is not None
            assert task.final_path == str(paths.final)
            cancelled = await session.get(DownloadTask, 2)
            assert cancelled is not None
            assert cancelled.status == TaskStatus.CANCELLED.value
        assert paths.final.read_bytes() == b"abcdef"
        assert not paths.temporary.exists()
        await database.engine.dispose()

    asyncio.run(run())
