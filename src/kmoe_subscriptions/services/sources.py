from __future__ import annotations

from collections.abc import Collection, Callable

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import Database
from ..external.bangumi import (
    BangumiClient,
    BangumiCollectionType,
    BangumiUserCollection,
)
from ..models import SubscriptionSource, SubscriptionSourceItem
from ..security import utcnow


def bangumi_source_config(
    source: SubscriptionSource,
) -> tuple[str, tuple[BangumiCollectionType, ...]]:
    username = source.config.get("username")
    raw_types = source.config.get("collection_types")
    if not isinstance(username, str) or not username:
        raise ValueError("Bangumi source has no valid username")
    if not isinstance(raw_types, list) or not raw_types:
        raise ValueError("Bangumi source has no collection types")
    try:
        collection_types = tuple(
            dict.fromkeys(BangumiCollectionType(value) for value in raw_types)
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("Bangumi source has invalid collection types") from exc
    return username, collection_types


async def reconcile_bangumi_items(
    session: AsyncSession,
    source: SubscriptionSource,
    collections: Collection[BangumiUserCollection],
) -> int:
    existing = {
        row.external_id: row
        for row in await session.scalars(
            select(SubscriptionSourceItem).where(
                SubscriptionSourceItem.source_id == source.id
            )
        )
    }
    seen: set[str] = set()
    now = utcnow()
    for collection in collections:
        subject = collection.subject
        if subject is None:
            continue
        external_id = str(subject.id)
        seen.add(external_id)
        row = existing.get(external_id)
        if row is None:
            row = SubscriptionSourceItem(
                source_id=source.id,
                external_id=external_id,
                title=subject.display_name,
                source_status=collection.collection_type.value,
                external_url=f"https://bgm.tv/subject/{subject.id}",
                search_query=subject.name_cn or subject.name,
            )
            session.add(row)
        row.title = subject.display_name
        row.original_title = subject.name or None
        row.source_status = collection.collection_type.value
        row.cover_url = subject.cover_url
        row.external_url = f"https://bgm.tv/subject/{subject.id}"
        row.search_query = subject.name_cn or subject.name
        row.last_seen_at = now

    stale = delete(SubscriptionSourceItem).where(
        SubscriptionSourceItem.source_id == source.id
    )
    if seen:
        stale = stale.where(SubscriptionSourceItem.external_id.not_in(seen))
    await session.execute(stale)
    source.last_success_at = now
    source.last_error_code = None
    source.last_error_message = None
    await session.flush()
    return len(seen)


async def sync_bangumi_source(
    database: Database,
    source_id: int,
    client_factory: Callable[[], BangumiClient],
) -> tuple[int, str | None]:
    """Sync one Bangumi source, persisting success or a structured failure."""
    async with database.sessions.begin() as session:
        source = await session.get(SubscriptionSource, source_id)
        if source is None:
            raise ValueError("Subscription source not found")
        username, collection_types = bangumi_source_config(source)
        source.last_attempt_at = utcnow()

    try:
        async with client_factory() as client:
            collections = await client.user_book_collections(
                username, collection_types
            )
    except httpx.HTTPStatusError as exc:
        error_code = (
            "bangumi_user_not_found"
            if exc.response.status_code == 404
            else "bangumi_unavailable"
        )
        await _record_failure(database, source_id, error_code)
        return 0, error_code
    except (httpx.HTTPError, ValueError):
        await _record_failure(database, source_id, "bangumi_unavailable")
        return 0, "bangumi_unavailable"

    async with database.sessions.begin() as session:
        source = await session.get(SubscriptionSource, source_id)
        if source is None:
            raise ValueError("Subscription source not found")
        imported = await reconcile_bangumi_items(session, source, collections)
    return imported, None


async def _record_failure(
    database: Database, source_id: int, error_code: str
) -> None:
    async with database.sessions.begin() as session:
        source = await session.get(SubscriptionSource, source_id)
        if source is None:
            return
        source.last_error_code = error_code
        source.last_error_message = "Unable to read the Bangumi collection"
