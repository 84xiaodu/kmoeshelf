from __future__ import annotations

from collections.abc import Collection

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..kmoe.schemas import ComicDetails, ContentType, DownloadFormat
from ..models import (
    Comic,
    DownloadTask,
    InitializationStrategy,
    RemoteItemRecord,
    Subscription,
)
from ..security import utcnow
from ..storage import library_directory


async def initialize_subscription(
    session: AsyncSession,
    details: ComicDetails,
    *,
    content_types: Collection[ContentType],
    download_format: DownloadFormat,
    strategy: InitializationStrategy,
) -> Subscription:
    selected = tuple(sorted({item.value for item in content_types}))
    if not selected:
        raise ValueError("At least one content type must be selected")

    comic = await session.scalar(select(Comic).where(Comic.remote_id == details.remote_id))
    if comic is None:
        comic = Comic(
            remote_id=details.remote_id,
            title=details.title,
            detail_path=details.detail_path,
            library_dir=library_directory(details.title, details.remote_id),
        )
        session.add(comic)
        await session.flush()
    elif comic.library_dir is None:
        comic.library_dir = library_directory(details.title, details.remote_id)
    comic.title = details.title
    comic.author = details.author
    comic.language = details.language
    comic.detail_path = details.detail_path
    comic.cover_url = details.cover_url
    comic.description = details.description

    subscription = await session.scalar(
        select(Subscription).where(Subscription.comic_id == comic.id)
    )
    if subscription is None:
        subscription = Subscription(
            comic_id=comic.id,
            content_types=list(selected),
            download_format=download_format.value,
            initialization_strategy=strategy.value,
        )
        session.add(subscription)
    else:
        subscription.content_types = list(selected)
        subscription.download_format = download_format.value
        subscription.initialization_strategy = strategy.value
        subscription.enabled = True

    existing_items = {
        (row.content_type, row.remote_id): row
        for row in (
            await session.scalars(
                select(RemoteItemRecord).where(RemoteItemRecord.comic_id == comic.id)
            )
        ).all()
    }
    now = utcnow()
    matching: list[RemoteItemRecord] = []
    for item in details.items:
        key = (item.content_type.value, item.remote_id)
        row = existing_items.get(key)
        if row is None:
            row = RemoteItemRecord(
                comic_id=comic.id,
                remote_id=item.remote_id,
                content_type=item.content_type.value,
                name=item.name,
            )
            session.add(row)
            existing_items[key] = row
        row.name = item.name
        row.sort_order = item.sort_order
        row.page_count = item.page_count
        row.mobi_size_mb = item.mobi_size_mb
        row.epub_size_mb = item.epub_size_mb
        row.last_seen_at = now
        if item.content_type.value in selected:
            matching.append(row)

    await session.flush()
    if strategy is InitializationStrategy.BACKFILL:
        existing_task_items = set(
            await session.scalars(
                select(DownloadTask.remote_item_id).where(
                    DownloadTask.remote_item_id.in_([row.id for row in matching]),
                    DownloadTask.download_format == download_format.value,
                )
            )
        )
        session.add_all(
            DownloadTask(remote_item_id=row.id, download_format=download_format.value)
            for row in matching
            if row.id not in existing_task_items
        )

    subscription.last_attempt_at = now
    subscription.last_success_at = now
    subscription.last_error_code = None
    subscription.last_error_message = None
    await session.flush()
    return subscription


async def refresh_subscription(session: AsyncSession, details: ComicDetails) -> int:
    comic = await session.scalar(select(Comic).where(Comic.remote_id == details.remote_id))
    if comic is None:
        raise ValueError("Comic is not subscribed")
    subscription = await session.scalar(
        select(Subscription).where(Subscription.comic_id == comic.id)
    )
    if subscription is None:
        raise ValueError("Comic is not subscribed")

    comic.title = details.title
    comic.author = details.author
    comic.language = details.language
    comic.detail_path = details.detail_path
    comic.cover_url = details.cover_url
    comic.description = details.description

    existing = {
        (row.content_type, row.remote_id): row
        for row in (
            await session.scalars(
                select(RemoteItemRecord).where(RemoteItemRecord.comic_id == comic.id)
            )
        ).all()
    }
    selected = set(subscription.content_types)
    discovered: list[RemoteItemRecord] = []
    now = utcnow()
    for item in details.items:
        key = (item.content_type.value, item.remote_id)
        row = existing.get(key)
        is_new = row is None
        if row is None:
            row = RemoteItemRecord(
                comic_id=comic.id,
                remote_id=item.remote_id,
                content_type=item.content_type.value,
                name=item.name,
            )
            session.add(row)
            existing[key] = row
        row.name = item.name
        row.sort_order = item.sort_order
        row.page_count = item.page_count
        row.mobi_size_mb = item.mobi_size_mb
        row.epub_size_mb = item.epub_size_mb
        row.last_seen_at = now
        if is_new and item.content_type.value in selected:
            discovered.append(row)

    await session.flush()
    if discovered:
        session.add_all(
            DownloadTask(
                remote_item_id=row.id,
                download_format=subscription.download_format,
            )
            for row in discovered
        )
    subscription.last_attempt_at = now
    subscription.last_success_at = now
    subscription.last_error_code = None
    subscription.last_error_message = None
    await session.flush()
    return len(discovered)
