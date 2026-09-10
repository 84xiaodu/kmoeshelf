from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from ..config import Settings
from ..db import Database
from ..external.bangumi import BangumiClient
from ..models import SubscriptionSource
from ..security import utcnow
from .sources import sync_bangumi_source


SYNC_CHECK_MINUTES = 15


def is_due(source: SubscriptionSource, now=None) -> bool:
    current = now or utcnow()
    if source.last_success_at is None:
        return True
    return current - source.last_success_at >= timedelta(
        hours=source.sync_interval_hours
    )


class SourceSyncService:
    def __init__(
        self,
        database: Database,
        settings: Settings,
        client_factory: Callable[[], BangumiClient],
    ) -> None:
        self.database = database
        self.settings = settings
        self.client_factory = client_factory
        self._scheduler: AsyncIOScheduler | None = None

    async def start(self) -> None:
        self._scheduler = AsyncIOScheduler(timezone="UTC")
        self._scheduler.add_job(
            self.sync_due_sources,
            "interval",
            minutes=SYNC_CHECK_MINUTES,
            id="subscription-source-sync",
            coalesce=True,
            max_instances=1,
        )
        self._scheduler.start()

    async def stop(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)

    async def sync_due_sources(self) -> int:
        async with self.database.sessions() as session:
            sources = list(
                await session.scalars(
                    select(SubscriptionSource).where(
                        SubscriptionSource.enabled.is_(True)
                    )
                )
            )
        synced = 0
        for source in sources:
            if not is_due(source):
                continue
            try:
                await sync_bangumi_source(
                    self.database, source.id, self.client_factory
                )
            except (ValueError, KeyError):
                continue
            synced += 1
        return synced
