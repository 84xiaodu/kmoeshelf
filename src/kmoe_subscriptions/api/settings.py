from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_db, require_csrf, require_same_origin, require_session
from ..models import AppSetting, Subscription
from ..kmoe.client import DEFAULT_MIRRORS
from ..security import utcnow


router = APIRouter(prefix="/api/settings", tags=["settings"])


class ApplicationSettings(BaseModel):
    check_interval_hours: int = Field(ge=1, le=24 * 30)
    download_concurrency: int = Field(ge=1, le=8)
    max_download_retries: int = Field(ge=0, le=10)
    preferred_mirror: str

    @field_validator("preferred_mirror")
    @classmethod
    def supported_mirror(cls, value: str) -> str:
        if value not in DEFAULT_MIRRORS:
            raise ValueError("unsupported Kmoe mirror")
        return value


async def app_setting(db: AsyncSession) -> AppSetting:
    row = await db.get(AppSetting, 1)
    if row is None:
        row = AppSetting(id=1)
        db.add(row)
        await db.flush()
    return row


@router.get(
    "",
    response_model=ApplicationSettings,
    dependencies=[Depends(require_session)],
)
async def get_schedule_settings(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApplicationSettings:
    row = await app_setting(db)
    return ApplicationSettings(
        check_interval_hours=row.check_interval_hours,
        download_concurrency=row.download_concurrency,
        max_download_retries=row.max_download_retries,
        preferred_mirror=row.preferred_mirror,
    )


@router.patch(
    "",
    response_model=ApplicationSettings,
    dependencies=[Depends(require_same_origin), Depends(require_csrf)],
)
async def update_schedule_settings(
    body: ApplicationSettings,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApplicationSettings:
    row = await app_setting(db)
    row.check_interval_hours = body.check_interval_hours
    row.download_concurrency = body.download_concurrency
    row.max_download_retries = body.max_download_retries
    row.preferred_mirror = body.preferred_mirror
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
