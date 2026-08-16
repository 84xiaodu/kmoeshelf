from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_db, get_settings, require_csrf, require_same_origin, require_session
from .kmoe import raise_kmoe_error, saved_client
from ..config import Settings
from ..kmoe.catalog import get_comic_details
from ..kmoe.errors import KmoeError
from ..kmoe.schemas import ContentType, DownloadFormat
from ..models import (
    ActivityEvent,
    AppSetting,
    Comic,
    DownloadTask,
    InitializationStrategy,
    RemoteItemRecord,
    Subscription,
    TaskStatus,
)
from ..services.subscriptions import initialize_subscription
from ..security import utcnow


router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])


class SubscriptionCreate(BaseModel):
    remote_id: str = Field(pattern=r"^[A-Za-z0-9]+$", max_length=128)
    content_types: set[ContentType] = Field(min_length=1)
    download_format: DownloadFormat
    initialization_strategy: InitializationStrategy


class SubscriptionEdit(BaseModel):
    content_types: set[ContentType] | None = Field(default=None, min_length=1)
    download_format: DownloadFormat | None = None


class SubscriptionView(BaseModel):
    id: int
    comic_id: int
    remote_id: str
    title: str
    author: str | None
    cover_url: str | None
    enabled: bool
    content_types: tuple[ContentType, ...]
    download_format: DownloadFormat
    initialization_strategy: InitializationStrategy
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    next_check_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None


async def get_subscription(
    db: AsyncSession, subscription_id: int
) -> tuple[Subscription, Comic]:
    row = (
        await db.execute(
            select(Subscription, Comic)
            .join(Comic, Comic.id == Subscription.comic_id)
            .where(Subscription.id == subscription_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return row[0], row[1]


def subscription_view(subscription: Subscription, comic: Comic) -> SubscriptionView:
    return SubscriptionView(
        id=subscription.id,
        comic_id=comic.id,
        remote_id=comic.remote_id,
        title=comic.title,
        author=comic.author,
        cover_url=comic.cover_url,
        enabled=subscription.enabled,
        content_types=tuple(ContentType(value) for value in subscription.content_types),
        download_format=DownloadFormat(subscription.download_format),
        initialization_strategy=InitializationStrategy(
            subscription.initialization_strategy
        ),
        last_attempt_at=subscription.last_attempt_at,
        last_success_at=subscription.last_success_at,
        next_check_at=subscription.next_check_at,
        last_error_code=subscription.last_error_code,
        last_error_message=subscription.last_error_message,
    )


async def schedule_next_check(db: AsyncSession, subscription: Subscription) -> None:
    setting = await db.get(AppSetting, 1)
    interval = setting.check_interval_hours if setting else 6
    subscription.next_check_at = utcnow() + timedelta(hours=interval)


@router.get("", response_model=list[SubscriptionView], dependencies=[Depends(require_session)])
async def list_subscriptions(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[SubscriptionView]:
    rows = (
        await db.execute(
            select(Subscription, Comic)
            .join(Comic, Comic.id == Subscription.comic_id)
            .order_by(Comic.title, Subscription.id)
        )
    ).all()
    return [subscription_view(subscription, comic) for subscription, comic in rows]


@router.post(
    "",
    response_model=SubscriptionView,
    status_code=201,
    dependencies=[Depends(require_same_origin), Depends(require_csrf)],
)
async def create_subscription(
    body: SubscriptionCreate,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SubscriptionView:
    existing = await db.scalar(
        select(Subscription.id)
        .join(Comic, Comic.id == Subscription.comic_id)
        .where(Comic.remote_id == body.remote_id)
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Comic is already subscribed")
    client, credential = await saved_client(request, settings, db)
    try:
        async with client:
            details = await get_comic_details(client, remote_id=body.remote_id)
    except KmoeError as exc:
        await raise_kmoe_error(exc, db=db, credential=credential)
    try:
        subscription = await initialize_subscription(
            db,
            details,
            content_types=body.content_types,
            download_format=body.download_format,
            strategy=body.initialization_strategy,
        )
        await schedule_next_check(db, subscription)
        db.add(
            ActivityEvent(
                event_type="subscription_created",
                comic_id=subscription.comic_id,
                message=f"Subscribed to {details.title}",
            )
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Comic is already subscribed") from exc
    comic = await db.get(Comic, subscription.comic_id)
    assert comic is not None
    return subscription_view(subscription, comic)


@router.patch(
    "/{subscription_id}",
    response_model=SubscriptionView,
    dependencies=[Depends(require_same_origin), Depends(require_csrf)],
)
async def edit_subscription(
    subscription_id: int,
    body: SubscriptionEdit,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SubscriptionView:
    subscription, comic = await get_subscription(db, subscription_id)
    if body.content_types is not None:
        subscription.content_types = sorted(value.value for value in body.content_types)
    if body.download_format is not None:
        subscription.download_format = body.download_format.value
    await db.commit()
    return subscription_view(subscription, comic)


async def set_enabled(
    subscription_id: int, *, enabled: bool, db: AsyncSession
) -> SubscriptionView:
    subscription, comic = await get_subscription(db, subscription_id)
    subscription.enabled = enabled
    if not enabled:
        subscription.next_check_at = None
    else:
        await schedule_next_check(db, subscription)
    await db.commit()
    return subscription_view(subscription, comic)


@router.post(
    "/{subscription_id}/pause",
    response_model=SubscriptionView,
    dependencies=[Depends(require_same_origin), Depends(require_csrf)],
)
async def pause_subscription(
    subscription_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SubscriptionView:
    return await set_enabled(subscription_id, enabled=False, db=db)


@router.post(
    "/{subscription_id}/resume",
    response_model=SubscriptionView,
    dependencies=[Depends(require_same_origin), Depends(require_csrf)],
)
async def resume_subscription(
    subscription_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SubscriptionView:
    return await set_enabled(subscription_id, enabled=True, db=db)


@router.delete(
    "/{subscription_id}",
    status_code=204,
    dependencies=[Depends(require_same_origin), Depends(require_csrf)],
)
async def delete_subscription(
    subscription_id: int,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    cancel_pending: Annotated[bool, Query()],
) -> Response:
    subscription, comic = await get_subscription(db, subscription_id)
    if cancel_pending:
        item_ids = select(RemoteItemRecord.id).where(
            RemoteItemRecord.comic_id == subscription.comic_id
        )
        await db.execute(
            update(DownloadTask)
            .where(
                DownloadTask.remote_item_id.in_(item_ids),
                DownloadTask.status == TaskStatus.PENDING.value,
            )
            .values(status=TaskStatus.CANCELLED.value)
        )
    await db.execute(delete(Subscription).where(Subscription.id == subscription.id))
    db.add(
        ActivityEvent(
            event_type="subscription_deleted",
            comic_id=comic.id,
            message=f"Unsubscribed from {comic.title}",
        )
    )
    await db.commit()
    response.status_code = 204
    return response
