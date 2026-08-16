from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_db, require_csrf, require_same_origin, require_session
from ..models import AppSetting, Subscription
from ..security import utcnow


router = APIRouter(prefix="/api/settings", tags=["settings"])


class ScheduleSettings(BaseModel):
    check_interval_hours: int = Field(ge=1, le=24 * 30)


async def app_setting(db: AsyncSession) -> AppSetting:
    row = await db.get(AppSetting, 1)
    if row is None:
        row = AppSetting(id=1)
        db.add(row)
        await db.flush()
    return row


@router.get(
    "",
    response_model=ScheduleSettings,
    dependencies=[Depends(require_session)],
)
async def get_schedule_settings(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ScheduleSettings:
    row = await app_setting(db)
    return ScheduleSettings(check_interval_hours=row.check_interval_hours)


@router.patch(
    "",
    response_model=ScheduleSettings,
    dependencies=[Depends(require_same_origin), Depends(require_csrf)],
)
async def update_schedule_settings(
    body: ScheduleSettings,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ScheduleSettings:
    row = await app_setting(db)
    row.check_interval_hours = body.check_interval_hours
    await db.execute(
        update(Subscription)
        .where(Subscription.enabled.is_(True))
        .values(
            next_check_at=utcnow() + timedelta(hours=body.check_interval_hours)
        )
    )
    await db.commit()
    request.app.state.check_service.reschedule(body.check_interval_hours)
    return body
