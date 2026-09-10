from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_db, require_csrf, require_same_origin, require_session
from ..external.bangumi import BangumiCollectionType
from ..models import SourceKind, SubscriptionSource, SubscriptionSourceItem
from ..services.sources import (
    bangumi_source_config,
    sync_bangumi_source,
)


router = APIRouter(prefix="/api/sources", tags=["sources"])
USERNAME = re.compile(r"^[A-Za-z0-9_-]+$")


class BangumiSourceInput(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    username: str = Field(min_length=1, max_length=64)
    collection_types: set[BangumiCollectionType] = Field(min_length=1)
    enabled: bool = True
    sync_interval_hours: int = Field(default=24, ge=1, le=24 * 30)

    @field_validator("name", "username")
    @classmethod
    def trim_values(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be blank")
        return value

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        if not USERNAME.fullmatch(value):
            raise ValueError("unsupported Bangumi username")
        return value


class SourceView(BaseModel):
    id: int
    source_type: SourceKind
    name: str
    enabled: bool
    username: str
    collection_types: tuple[BangumiCollectionType, ...]
    sync_interval_hours: int
    item_count: int
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None


class SourceItemView(BaseModel):
    id: int
    source_id: int
    external_id: str
    title: str
    original_title: str | None
    source_status: BangumiCollectionType
    cover_url: str | None
    external_url: str
    search_query: str
    first_seen_at: datetime
    last_seen_at: datetime


class SourceSyncView(BaseModel):
    source: SourceView
    imported_count: int


async def get_source(db: AsyncSession, source_id: int) -> SubscriptionSource:
    source = await db.get(SubscriptionSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Subscription source not found")
    return source


def source_view(source: SubscriptionSource, item_count: int) -> SourceView:
    username, collection_types = bangumi_source_config(source)
    return SourceView(
        id=source.id,
        source_type=SourceKind(source.source_type),
        name=source.name,
        enabled=source.enabled,
        username=username,
        collection_types=collection_types,
        sync_interval_hours=source.sync_interval_hours,
        item_count=item_count,
        last_attempt_at=source.last_attempt_at,
        last_success_at=source.last_success_at,
        last_error_code=source.last_error_code,
        last_error_message=source.last_error_message,
    )


async def source_count(db: AsyncSession, source_id: int) -> int:
    return (
        await db.scalar(
            select(func.count(SubscriptionSourceItem.id)).where(
                SubscriptionSourceItem.source_id == source_id
            )
        )
        or 0
    )


@router.get("", response_model=list[SourceView], dependencies=[Depends(require_session)])
async def list_sources(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[SourceView]:
    sources = list(
        await db.scalars(select(SubscriptionSource).order_by(SubscriptionSource.id))
    )
    count_rows = (
        await db.execute(
            select(
                SubscriptionSourceItem.source_id,
                func.count(SubscriptionSourceItem.id),
            ).group_by(SubscriptionSourceItem.source_id)
        )
    ).all()
    counts = {source_id: count for source_id, count in count_rows}
    return [source_view(source, counts.get(source.id, 0)) for source in sources]


@router.post(
    "",
    response_model=SourceView,
    status_code=201,
    dependencies=[Depends(require_same_origin), Depends(require_csrf)],
)
async def create_source(
    body: BangumiSourceInput,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SourceView:
    source = SubscriptionSource(
        source_type=SourceKind.BANGUMI.value,
        name=body.name,
        enabled=body.enabled,
        sync_interval_hours=body.sync_interval_hours,
        config={
            "username": body.username,
            "collection_types": [
                value.value
                for value in sorted(
                    body.collection_types, key=lambda value: value.api_value
                )
            ],
        },
    )
    db.add(source)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Subscription source already exists") from exc
    return source_view(source, 0)


@router.patch(
    "/{source_id}",
    response_model=SourceView,
    dependencies=[Depends(require_same_origin), Depends(require_csrf)],
)
async def edit_source(
    source_id: int,
    body: BangumiSourceInput,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SourceView:
    source = await get_source(db, source_id)
    source.name = body.name
    source.enabled = body.enabled
    source.sync_interval_hours = body.sync_interval_hours
    source.config = {
        "username": body.username,
        "collection_types": [
            value.value
            for value in sorted(body.collection_types, key=lambda value: value.api_value)
        ],
    }
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Subscription source already exists") from exc
    return source_view(source, await source_count(db, source.id))


@router.get(
    "/{source_id}/items",
    response_model=list[SourceItemView],
    dependencies=[Depends(require_session)],
)
async def list_source_items(
    source_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[SourceItemView]:
    await get_source(db, source_id)
    items = list(
        await db.scalars(
            select(SubscriptionSourceItem)
            .where(SubscriptionSourceItem.source_id == source_id)
            .order_by(
                SubscriptionSourceItem.source_status,
                SubscriptionSourceItem.title,
            )
        )
    )
    return [
        SourceItemView(
            id=item.id,
            source_id=item.source_id,
            external_id=item.external_id,
            title=item.title,
            original_title=item.original_title,
            source_status=BangumiCollectionType(item.source_status),
            cover_url=item.cover_url,
            external_url=item.external_url,
            search_query=item.search_query,
            first_seen_at=item.first_seen_at,
            last_seen_at=item.last_seen_at,
        )
        for item in items
    ]


@router.post(
    "/{source_id}/sync",
    response_model=SourceSyncView,
    dependencies=[Depends(require_same_origin), Depends(require_csrf)],
)
async def sync_source(
    source_id: int,
    request: Request,
) -> SourceSyncView:
    database = request.app.state.database
    async with database.sessions() as session:
        source = await session.get(SubscriptionSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Subscription source not found")
    if source.source_type != SourceKind.BANGUMI.value:
        raise HTTPException(status_code=422, detail="Unsupported subscription source")
    try:
        imported, error_code = await sync_bangumi_source(
            database, source_id, request.app.state.bangumi_client_factory
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Subscription source not found") from exc
    if error_code is not None:
        status = 404 if error_code == "bangumi_user_not_found" else 502
        raise HTTPException(
            status_code=status,
            detail={
                "code": error_code,
                "message": "Unable to read the Bangumi collection",
            },
        )
    async with database.sessions() as session:
        source = await session.get(SubscriptionSource, source_id)
        assert source is not None
        return SourceSyncView(
            source=source_view(source, imported),
            imported_count=imported,
        )


@router.delete(
    "/{source_id}",
    status_code=204,
    dependencies=[Depends(require_same_origin), Depends(require_csrf)],
)
async def delete_source(
    source_id: int,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    await get_source(db, source_id)
    await db.execute(
        delete(SubscriptionSource).where(SubscriptionSource.id == source_id)
    )
    await db.commit()
    response.status_code = 204
    return response
