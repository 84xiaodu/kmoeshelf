from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy import func, select

from kmoe_subscriptions.db import create_database
from kmoe_subscriptions.kmoe.schemas import (
    ComicDetails,
    ContentType,
    DownloadFormat,
    RemoteItem,
)
from kmoe_subscriptions.main import migrate
from kmoe_subscriptions.models import (
    Comic,
    DownloadTask,
    InitializationStrategy,
    RemoteItemRecord,
    Subscription,
    TaskStatus,
)
from kmoe_subscriptions.services.subscription_policy import reconcile_policy
from kmoe_subscriptions.services.subscriptions import (
    initialize_subscription,
    refresh_subscription,
)


def details() -> ComicDetails:
    return ComicDetails(
        remote_id="50076",
        title="Test comic",
        detail_path="/c/50076.htm",
        items=(
            RemoteItem(remote_id="101", content_type=ContentType.VOLUME, name="Volume 1"),
            RemoteItem(remote_id="201", content_type=ContentType.EXTRA, name="Extra 1"),
        ),
    )


def test_future_only_records_baseline_without_tasks(tmp_path: Path) -> None:
    async def run() -> None:
        url = f"sqlite+aiosqlite:///{tmp_path / 'future.db'}"
        await migrate(url)
        database = create_database(url)
        async with database.sessions.begin() as session:
            await initialize_subscription(
                session,
                details(),
                content_types={ContentType.VOLUME, ContentType.EXTRA},
                download_format=DownloadFormat.EPUB,
                strategy=InitializationStrategy.FUTURE_ONLY,
            )
        async with database.sessions() as session:
            assert await session.scalar(select(func.count(RemoteItemRecord.id))) == 2
            assert await session.scalar(select(func.count(DownloadTask.id))) == 0
            comic = await session.scalar(select(Comic))
            assert comic is not None
            assert comic.library_dir == "Test comic [50076]"
        await database.engine.dispose()

    asyncio.run(run())


def test_backfill_filters_types_and_is_idempotent(tmp_path: Path) -> None:
    async def run() -> None:
        url = f"sqlite+aiosqlite:///{tmp_path / 'backfill.db'}"
        await migrate(url)
        database = create_database(url)
        for _ in range(2):
            async with database.sessions.begin() as session:
                await initialize_subscription(
                    session,
                    details(),
                    content_types={ContentType.VOLUME},
                    download_format=DownloadFormat.MOBI,
                    strategy=InitializationStrategy.BACKFILL,
                )
        async with database.sessions() as session:
            tasks = (await session.scalars(select(DownloadTask))).all()
            assert len(tasks) == 1
            assert tasks[0].download_format == DownloadFormat.MOBI.value
        await database.engine.dispose()

    asyncio.run(run())


def test_refresh_only_queues_new_selected_items(tmp_path: Path) -> None:
    async def run() -> None:
        url = f"sqlite+aiosqlite:///{tmp_path / 'refresh.db'}"
        await migrate(url)
        database = create_database(url)
        async with database.sessions.begin() as session:
            await initialize_subscription(
                session,
                details(),
                content_types={ContentType.VOLUME},
                download_format=DownloadFormat.EPUB,
                strategy=InitializationStrategy.FUTURE_ONLY,
            )

        refreshed = details().model_copy(
            update={
                "items": details().items
                + (
                    RemoteItem(
                        remote_id="102",
                        content_type=ContentType.VOLUME,
                        name="Volume 2",
                    ),
                    RemoteItem(
                        remote_id="202",
                        content_type=ContentType.EXTRA,
                        name="Extra 2",
                    ),
                )
            }
        )
        for expected in (1, 0):
            async with database.sessions.begin() as session:
                assert await refresh_subscription(session, refreshed) == expected

        async with database.sessions() as session:
            tasks = (await session.scalars(select(DownloadTask))).all()
            assert len(tasks) == 1
        await database.engine.dispose()

    asyncio.run(run())


def test_policy_preview_and_apply_convert_and_backfill_tasks(tmp_path: Path) -> None:
    async def run() -> None:
        url = f"sqlite+aiosqlite:///{tmp_path / 'policy.db'}"
        await migrate(url)
        database = create_database(url)
        async with database.sessions.begin() as session:
            subscription = await initialize_subscription(
                session,
                details(),
                content_types={ContentType.VOLUME},
                download_format=DownloadFormat.EPUB,
                strategy=InitializationStrategy.BACKFILL,
            )
            task = await session.scalar(select(DownloadTask))
            assert task is not None
            task.status = TaskStatus.FAILED.value
            task.attempt_count = 4
            task.error_code = "download_forbidden"

        async with database.sessions.begin() as session:
            subscription = await session.scalar(select(Subscription))
            assert subscription is not None
            preview = await reconcile_policy(
                session,
                subscription,
                content_types={ContentType.VOLUME, ContentType.EXTRA},
                download_format=DownloadFormat.MOBI,
                strategy=InitializationStrategy.BACKFILL,
                apply=False,
            )
            assert preview.converted == 1
            assert preview.created == 1
            assert subscription.download_format == DownloadFormat.EPUB.value

        async with database.sessions.begin() as session:
            subscription = await session.scalar(select(Subscription))
            assert subscription is not None
            impact = await reconcile_policy(
                session,
                subscription,
                content_types={ContentType.VOLUME, ContentType.EXTRA},
                download_format=DownloadFormat.MOBI,
                strategy=InitializationStrategy.BACKFILL,
                apply=True,
            )
            assert impact.converted == 1
            assert impact.created == 1

        async with database.sessions() as session:
            tasks = list(
                await session.scalars(select(DownloadTask).order_by(DownloadTask.id))
            )
            assert [(task.download_format, task.status) for task in tasks] == [
                (DownloadFormat.MOBI.value, TaskStatus.PENDING.value),
                (DownloadFormat.MOBI.value, TaskStatus.PENDING.value),
            ]
            assert tasks[0].attempt_count == 0
            assert tasks[0].error_code is None
        await database.engine.dispose()

    asyncio.run(run())
