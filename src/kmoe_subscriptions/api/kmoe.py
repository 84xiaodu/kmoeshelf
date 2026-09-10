from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_db, get_settings, require_csrf, require_same_origin, require_session
from ..config import Settings
from ..kmoe.auth import login, validate_session
from ..kmoe.catalog import SearchTargetCache, get_comic_details, search_catalog
from ..kmoe.client import DEFAULT_MIRRORS, KmoeClient
from ..kmoe.credentials import decrypt_cookies, encrypt_cookies
from ..kmoe.errors import AuthenticationExpired, KmoeError
from ..kmoe.schemas import ComicDetails, KmoeAccountUsage, SearchPage
from ..models import AppSetting, KmoeCredential
from ..security import utcnow


router = APIRouter(prefix="/api/kmoe", tags=["kmoe"])


class KmoeLoginInput(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        if value != value.strip() or any(character.isspace() for character in value):
            raise ValueError("email must not contain whitespace")
        local, separator, domain = value.rpartition("@")
        if separator != "@" or not local or "." not in domain:
            raise ValueError("email must be a valid address")
        return value


class QuotaUsageView(BaseModel):
    total_mb: float | None
    used_mb: float | None
    remaining_mb: float | None
    reset_day: int | None


class KmoeUsageView(BaseModel):
    user_level: int | None
    is_vip: bool | None
    free: QuotaUsageView | None
    vip: QuotaUsageView | None
    checked_at: datetime | None


class KmoeStatus(BaseModel):
    connected: bool
    email: str | None = None
    mirror: str | None = None
    status: str | None = None
    usage: KmoeUsageView | None = None


def kmoe_client(request: Request) -> KmoeClient:
    return request.app.state.kmoe_client_factory()


def quota_view(
    total: Decimal | None, used: Decimal | None, reset_day: int | None
) -> QuotaUsageView | None:
    if total is None and used is None and reset_day is None:
        return None
    total_value = float(total) if total is not None else None
    used_value = float(used) if used is not None else None
    remaining = (
        max(0.0, total_value - used_value)
        if total_value is not None and used_value is not None
        else None
    )
    return QuotaUsageView(
        total_mb=total_value,
        used_mb=used_value,
        remaining_mb=remaining,
        reset_day=reset_day,
    )


def usage_view(credential: KmoeCredential) -> KmoeUsageView | None:
    free = quota_view(
        credential.free_quota_total_mb,
        credential.free_quota_used_mb,
        credential.free_quota_reset_day,
    )
    vip = quota_view(
        credential.vip_quota_total_mb,
        credential.vip_quota_used_mb,
        credential.vip_quota_reset_day,
    )
    if free is None and vip is None and credential.user_level is None:
        return None
    return KmoeUsageView(
        user_level=credential.user_level,
        is_vip=credential.is_vip,
        free=free,
        vip=vip,
        checked_at=credential.quota_checked_at,
    )


def status_view(credential: KmoeCredential) -> KmoeStatus:
    return KmoeStatus(
        connected=credential.status == "active",
        email=credential.email,
        mirror=credential.active_mirror,
        status=credential.status,
        usage=usage_view(credential),
    )


def apply_usage(
    credential: KmoeCredential, usage: KmoeAccountUsage | None
) -> None:
    credential.user_level = usage.user_level if usage else None
    credential.is_vip = usage.is_vip if usage else None
    credential.free_quota_total_mb = usage.free.total_mb if usage and usage.free else None
    credential.free_quota_used_mb = usage.free.used_mb if usage and usage.free else None
    credential.free_quota_reset_day = usage.free.reset_day if usage and usage.free else None
    credential.vip_quota_total_mb = usage.vip.total_mb if usage and usage.vip else None
    credential.vip_quota_used_mb = usage.vip.used_mb if usage and usage.vip else None
    credential.vip_quota_reset_day = usage.vip.reset_day if usage and usage.vip else None
    credential.quota_checked_at = utcnow()


def error_status(code: str) -> int:
    if code in {"invalid_credentials", "auth_expired"}:
        return 401
    if code == "account_disabled":
        return 403
    if code == "auth_challenge":
        return 409
    if code == "not_found":
        return 404
    if code == "rate_limited":
        return 429
    if code == "credential_decryption_failed":
        return 500
    return 502


async def saved_client(
    request: Request,
    settings: Settings,
    db: AsyncSession,
) -> tuple[KmoeClient, KmoeCredential]:
    credential = await db.get(KmoeCredential, 1)
    if credential is None or credential.status != "active":
        raise HTTPException(
            status_code=409,
            detail={"code": "kmoe_not_connected", "message": "Kmoe login required"},
        )
    try:
        snapshot = decrypt_cookies(settings, credential.encrypted_cookies)
    except KmoeError as exc:
        await raise_kmoe_error(exc, db=db, credential=credential)
    client = kmoe_client(request)
    client.active_mirror = snapshot.mirror
    client.set_cookies(snapshot.cookies, domain=snapshot.mirror)
    return client, credential


async def raise_kmoe_error(
    exc: KmoeError,
    *,
    db: AsyncSession,
    credential: KmoeCredential | None = None,
) -> NoReturn:
    if credential is not None and isinstance(exc, AuthenticationExpired):
        credential.status = "expired"
        await db.commit()
    raise HTTPException(
        status_code=error_status(exc.code),
        detail={"code": exc.code, "message": str(exc)},
    ) from exc


@router.get("/status", response_model=KmoeStatus, dependencies=[Depends(require_session)])
async def status(db: Annotated[AsyncSession, Depends(get_db)]) -> KmoeStatus:
    credential = await db.get(KmoeCredential, 1)
    if credential is None:
        return KmoeStatus(connected=False)
    return status_view(credential)


@router.post(
    "/status/refresh",
    response_model=KmoeStatus,
    dependencies=[Depends(require_same_origin), Depends(require_csrf)],
)
async def refresh_status(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KmoeStatus:
    client, credential = await saved_client(request, settings, db)
    try:
        async with client:
            usage = await validate_session(client)
    except KmoeError as exc:
        await raise_kmoe_error(exc, db=db, credential=credential)
    apply_usage(credential, usage)
    credential.status = "active"
    credential.last_validated_at = utcnow()
    await db.commit()
    return status_view(credential)


@router.post(
    "/login",
    response_model=KmoeStatus,
    dependencies=[Depends(require_same_origin), Depends(require_csrf)],
)
async def connect(
    body: KmoeLoginInput,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KmoeStatus:
    client = kmoe_client(request)
    setting = await db.get(AppSetting, 1)
    preferred = setting.preferred_mirror if setting else DEFAULT_MIRRORS[0]
    if preferred in DEFAULT_MIRRORS:
        client.active_mirror = preferred
    try:
        async with client:
            authenticated = await login(client, email=body.email, password=body.password)
    except KmoeError as exc:
        await raise_kmoe_error(exc, db=db)

    credential = await db.get(KmoeCredential, 1)
    if credential is None:
        credential = KmoeCredential(
            id=1,
            email=body.email,
            encrypted_cookies="",
            active_mirror=authenticated.mirror,
        )
        db.add(credential)
    credential.email = body.email
    credential.encrypted_cookies = encrypt_cookies(
        settings,
        mirror=authenticated.mirror,
        cookies=authenticated.cookies,
    )
    credential.active_mirror = authenticated.mirror
    credential.status = "active"
    credential.last_validated_at = utcnow()
    apply_usage(credential, authenticated.usage)
    await db.commit()
    return status_view(credential)


@router.get(
    "/search",
    response_model=SearchPage,
    dependencies=[Depends(require_session)],
)
async def search(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
    query: Annotated[str, Query(alias="q", min_length=1, max_length=200)],
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
) -> SearchPage:
    client, credential = await saved_client(request, settings, db)
    target_cache: SearchTargetCache = request.app.state.search_target_cache
    try:
        async with client:
            return await search_catalog(
                client,
                query=query,
                page=page,
                target_cache=target_cache,
            )
    except KmoeError as exc:
        target_cache.invalidate()
        await raise_kmoe_error(exc, db=db, credential=credential)


@router.get(
    "/comics/{remote_id}",
    response_model=ComicDetails,
    dependencies=[Depends(require_session)],
)
async def comic_details(
    remote_id: Annotated[str, Path(pattern=r"^[A-Za-z0-9]+$", max_length=128)],
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ComicDetails:
    client, credential = await saved_client(request, settings, db)
    try:
        async with client:
            return await get_comic_details(client, remote_id=remote_id)
    except KmoeError as exc:
        await raise_kmoe_error(exc, db=db, credential=credential)
