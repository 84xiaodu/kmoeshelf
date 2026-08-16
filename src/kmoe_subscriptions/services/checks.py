from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..db import Database
from ..kmoe.catalog import get_comic_details
from ..kmoe.client import KmoeClient
from ..kmoe.credentials import decrypt_cookies
from ..kmoe.errors import AuthenticationExpired, KmoeError
from ..models import (
    ActivityEvent,
    AppSetting,
    CheckBatch,
    CheckStatus,
    Comic,
    KmoeCredential,
    Subscription,
    SubscriptionCheck,
)
from ..security import utcnow
from .subscriptions import refresh_subscription


ACTIVE_CHECK_STATUSES = (CheckStatus.PENDING.value, CheckStatus.RUNNING.value)


@dataclass(frozen=True, slots=True)
class EnqueueResult:
    batch_id: int
    queued_count: int
    created: bool


class CheckService:
    def __init__(
        self,
        database: Database,
        settings: Settings,
        client_factory: Callable[[], KmoeClient],
        download_wake: Callable[[], None] | None = None,
    ) -> None:
        self.database = database
        self.settings = settings
        self.client_factory = client_factory
        self.download_wake = download_wake
        self._scheduler: AsyncIOScheduler | None = None
        self._workers: list[asyncio.Task[None]] = []
        self._wake = asyncio.Event()
        self._stopping = False
        self._enqueue_lock = asyncio.Lock()

    async def start(self) -> None:
        async with self.database.sessions.begin() as session:
            recovering_batches = list(
                await session.scalars(
                    select(CheckBatch.id).where(
                        CheckBatch.status == CheckStatus.RUNNING.value
                    )
                )
            )
            await session.execute(
                update(SubscriptionCheck)
                .where(SubscriptionCheck.status == CheckStatus.RUNNING.value)
                .values(status=CheckStatus.PENDING.value, started_at=None)
            )
            await session.execute(
                update(CheckBatch)
                .where(CheckBatch.status == CheckStatus.RUNNING.value)
                .values(status=CheckStatus.PENDING.value, started_at=None)
            )
            app_setting = await session.get(AppSetting, 1)
            if app_setting is None:
                app_setting = AppSetting(id=1)
                session.add(app_setting)
                await session.flush()
            interval_hours = app_setting.check_interval_hours
            concurrency = app_setting.check_concurrency
        for batch_id in recovering_batches:
            await self._finish_batch(batch_id)
        self._scheduler = AsyncIOScheduler(timezone="UTC")
        self._scheduler.add_job(
            self.enqueue_all,
            "interval",
            hours=interval_hours,
            id="subscription-checks",
            coalesce=True,
            max_instances=1,
            kwargs={"trigger": "scheduled"},
        )
        self._scheduler.start()
        self._workers = [
            asyncio.create_task(self._worker(), name=f"subscription-check-{index}")
            for index in range(max(1, concurrency))
        ]
        self._wake.set()

    async def stop(self) -> None:
        self._stopping = True
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
        self._wake.set()
        if self._workers:
            await asyncio.gather(*self._workers)

    def reschedule(self, interval_hours: int) -> None:
        if self._scheduler is None:
            raise RuntimeError("Check scheduler is not running")
        self._scheduler.reschedule_job(
            "subscription-checks", trigger="interval", hours=interval_hours
        )

    async def enqueue_all(self, *, trigger: str = "manual_all") -> EnqueueResult:
        async with self._enqueue_lock:
            async with self.database.sessions.begin() as session:
                active = await session.scalar(
                    select(CheckBatch.id)
                    .where(CheckBatch.status.in_(ACTIVE_CHECK_STATUSES))
                    .order_by(CheckBatch.id)
                    .limit(1)
                )
                if active is not None:
                    count = await session.scalar(
                        select(func.count(SubscriptionCheck.id)).where(
                            SubscriptionCheck.batch_id == active
                        )
                    )
                    return EnqueueResult(active, count or 0, False)
                batch = CheckBatch(trigger=trigger)
                session.add(batch)
                await session.flush()
                subscription_ids = list(
                    await session.scalars(
                        select(Subscription.id)
                        .where(Subscription.enabled.is_(True))
                        .order_by(Subscription.id)
                    )
                )
                session.add_all(
                    SubscriptionCheck(batch_id=batch.id, subscription_id=value)
                    for value in subscription_ids
                )
                if not subscription_ids:
                    batch.status = CheckStatus.COMPLETED.value
                    batch.completed_at = utcnow()
                await self._set_next_check_times(session, subscription_ids)
                result = EnqueueResult(batch.id, len(subscription_ids), True)
            if result.queued_count:
                self._wake.set()
            return result

    async def enqueue_one(self, subscription_id: int) -> EnqueueResult:
        async with self._enqueue_lock:
            async with self.database.sessions.begin() as session:
                if await session.get(Subscription, subscription_id) is None:
                    raise ValueError("Subscription not found")
                active = await session.scalar(
                    select(SubscriptionCheck.batch_id)
                    .join(CheckBatch, CheckBatch.id == SubscriptionCheck.batch_id)
                    .where(
                        SubscriptionCheck.subscription_id == subscription_id,
                        SubscriptionCheck.status.in_(ACTIVE_CHECK_STATUSES),
                        CheckBatch.status.in_(ACTIVE_CHECK_STATUSES),
                    )
                    .limit(1)
                )
                if active is not None:
                    return EnqueueResult(active, 1, False)
                batch = CheckBatch(trigger="manual_single")
                session.add(batch)
                await session.flush()
                session.add(
                    SubscriptionCheck(
                        batch_id=batch.id,
                        subscription_id=subscription_id,
                    )
                )
                await self._set_next_check_times(session, [subscription_id])
                result = EnqueueResult(batch.id, 1, True)
            self._wake.set()
            return result

    async def _set_next_check_times(
        self, session: AsyncSession, subscription_ids: list[int]
    ) -> None:
        if not subscription_ids:
            return
        app_setting = await session.get(AppSetting, 1)
        interval = app_setting.check_interval_hours if app_setting else 6
        await session.execute(
            update(Subscription)
            .where(Subscription.id.in_(subscription_ids))
            .values(next_check_at=utcnow() + timedelta(hours=interval))
        )

    async def _worker(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            while check := await self._claim():
                await self._process(*check)
            if self._stopping:
                return

    async def _claim(self) -> tuple[int, int, int] | None:
        async with self.database.sessions.begin() as session:
            candidate = (
                select(SubscriptionCheck.id)
                .where(SubscriptionCheck.status == CheckStatus.PENDING.value)
                .order_by(SubscriptionCheck.id)
                .limit(1)
                .scalar_subquery()
            )
            row = (
                await session.execute(
                    update(SubscriptionCheck)
                    .where(
                        SubscriptionCheck.id == candidate,
                        SubscriptionCheck.status == CheckStatus.PENDING.value,
                    )
                    .values(status=CheckStatus.RUNNING.value, started_at=utcnow())
                    .returning(
                        SubscriptionCheck.id,
                        SubscriptionCheck.batch_id,
                        SubscriptionCheck.subscription_id,
                    )
                )
            ).one_or_none()
            if row is None:
                return None
            await session.execute(
                update(CheckBatch)
                .where(
                    CheckBatch.id == row.batch_id,
                    CheckBatch.status == CheckStatus.PENDING.value,
                )
                .values(status=CheckStatus.RUNNING.value, started_at=utcnow())
            )
            return row.id, row.batch_id, row.subscription_id

    async def _process(
        self, check_id: int, batch_id: int, subscription_id: int
    ) -> None:
        try:
            async with self.database.sessions() as session:
                subscription = await session.get(Subscription, subscription_id)
                if subscription is None:
                    return
                comic = await session.get(Comic, subscription.comic_id)
                credential = await session.get(KmoeCredential, 1)
                if comic is None:
                    raise RuntimeError("Subscription comic is missing")
                if credential is None or credential.status != "active":
                    raise AuthenticationExpired("Kmoe login required")
                snapshot = decrypt_cookies(self.settings, credential.encrypted_cookies)
                remote_id = comic.remote_id
            client = self.client_factory()
            client.active_mirror = snapshot.mirror
            client.set_cookies(snapshot.cookies, domain=snapshot.mirror)
            async with client:
                details = await get_comic_details(client, remote_id=remote_id)
            async with self.database.sessions.begin() as session:
                check = await session.get(SubscriptionCheck, check_id)
                subscription = await session.get(Subscription, subscription_id)
                if check is None or subscription is None:
                    return
                discovered = await refresh_subscription(session, details)
                await self._set_next_check_times(session, [subscription_id])
                check.status = CheckStatus.COMPLETED.value
                check.discovered_count = discovered
                check.completed_at = utcnow()
                if discovered:
                    session.add(
                        ActivityEvent(
                            event_type="new_content_discovered",
                            comic_id=subscription.comic_id,
                            message=f"Discovered {discovered} new item(s) for {details.title}",
                        )
                    )
                    if self.download_wake is not None:
                        self.download_wake()
        except KmoeError as exc:
            await self._fail_check(check_id, subscription_id, exc.code, str(exc), exc)
        except Exception as exc:
            await self._fail_check(
                check_id,
                subscription_id,
                "internal_error",
                f"Check failed with {type(exc).__name__}",
                exc,
            )
        finally:
            await self._finish_batch(batch_id)

    async def _fail_check(
        self,
        check_id: int,
        subscription_id: int,
        code: str,
        message: str,
        error: Exception,
    ) -> None:
        async with self.database.sessions.begin() as session:
            check = await session.get(SubscriptionCheck, check_id)
            subscription = await session.get(Subscription, subscription_id)
            if check is not None:
                check.status = CheckStatus.FAILED.value
                check.error_code = code
                check.error_message = message
                check.completed_at = utcnow()
            if subscription is not None:
                subscription.last_attempt_at = utcnow()
                subscription.last_error_code = code
                subscription.last_error_message = message
                await self._set_next_check_times(session, [subscription_id])
                session.add(
                    ActivityEvent(
                        event_type="subscription_check_failed",
                        comic_id=subscription.comic_id,
                        message=f"Subscription check failed: {code}",
                    )
                )
            if isinstance(error, AuthenticationExpired):
                credential = await session.get(KmoeCredential, 1)
                if credential is not None:
                    credential.status = "expired"

    async def _finish_batch(self, batch_id: int) -> None:
        async with self.database.sessions.begin() as session:
            batch = await session.get(CheckBatch, batch_id)
            if batch is None or batch.status not in ACTIVE_CHECK_STATUSES:
                return
            active = await session.scalar(
                select(func.count(SubscriptionCheck.id)).where(
                    SubscriptionCheck.batch_id == batch_id,
                    SubscriptionCheck.status.in_(ACTIVE_CHECK_STATUSES),
                )
            )
            if active:
                return
            failed = await session.scalar(
                select(func.count(SubscriptionCheck.id)).where(
                    SubscriptionCheck.batch_id == batch_id,
                    SubscriptionCheck.status == CheckStatus.FAILED.value,
                )
            )
            batch.status = (
                CheckStatus.FAILED.value if failed else CheckStatus.COMPLETED.value
            )
            batch.completed_at = utcnow()
            session.add(
                ActivityEvent(
                    event_type="subscription_check_finished",
                    comic_id=None,
                    message=f"Subscription check batch {batch.id} finished",
                )
            )
