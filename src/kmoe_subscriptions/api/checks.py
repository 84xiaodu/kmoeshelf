from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_db, require_csrf, require_same_origin, require_session
from ..models import CheckBatch, CheckStatus, SubscriptionCheck
from ..services.checks import CheckService, EnqueueResult


router = APIRouter(prefix="/api/checks", tags=["checks"])


class CheckEnqueueView(BaseModel):
    batch_id: int
    queued_count: int
    created: bool


class CheckBatchView(BaseModel):
    id: int
    trigger: str
    status: CheckStatus
    queued_count: int
    completed_count: int
    failed_count: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


def check_service(request: Request) -> CheckService:
    return request.app.state.check_service


def enqueue_view(result: EnqueueResult) -> CheckEnqueueView:
    return CheckEnqueueView(
        batch_id=result.batch_id,
        queued_count=result.queued_count,
        created=result.created,
    )


@router.post(
    "",
    response_model=CheckEnqueueView,
    status_code=202,
    dependencies=[Depends(require_same_origin), Depends(require_csrf)],
)
async def check_all(request: Request) -> CheckEnqueueView:
    return enqueue_view(await check_service(request).enqueue_all())


@router.post(
    "/subscriptions/{subscription_id}",
    response_model=CheckEnqueueView,
    status_code=202,
    dependencies=[Depends(require_same_origin), Depends(require_csrf)],
)
async def check_one(subscription_id: int, request: Request) -> CheckEnqueueView:
    try:
        result = await check_service(request).enqueue_one(subscription_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Subscription not found") from exc
    return enqueue_view(result)


@router.get(
    "/{batch_id}",
    response_model=CheckBatchView,
    dependencies=[Depends(require_session)],
)
async def batch_status(
    batch_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CheckBatchView:
    batch = await db.get(CheckBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Check batch not found")

    async def count(status: CheckStatus | None = None) -> int:
        statement = select(func.count(SubscriptionCheck.id)).where(
            SubscriptionCheck.batch_id == batch_id
        )
        if status is not None:
            statement = statement.where(SubscriptionCheck.status == status.value)
        return await db.scalar(statement) or 0

    return CheckBatchView(
        id=batch.id,
        trigger=batch.trigger,
        status=CheckStatus(batch.status),
        queued_count=await count(),
        completed_count=await count(CheckStatus.COMPLETED),
        failed_count=await count(CheckStatus.FAILED),
        created_at=batch.created_at,
        started_at=batch.started_at,
        completed_at=batch.completed_at,
    )
