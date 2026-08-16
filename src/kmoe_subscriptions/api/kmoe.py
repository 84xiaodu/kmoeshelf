from __future__ import annotations

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_db, get_settings, require_csrf, require_same_origin, require_session
from ..config import Settings
from ..kmoe.auth import login
from ..kmoe.catalog import get_comic_details, search_catalog
from ..kmoe.client import KmoeClient
from ..kmoe.credentials import decrypt_cookies, encrypt_cookies
from ..kmoe.errors import AuthenticationExpired, KmoeError
from ..kmoe.schemas import ComicDetails, SearchPage
from ..models import KmoeCredential
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


class KmoeStatus(BaseModel):
    connected: bool
    email: str | None = None
    mirror: str | None = None
    status: str | None = None


def kmoe_client(request: Request) -> KmoeClient:
    return request.app.state.kmoe_client_factory()


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
    return KmoeStatus(
        connected=credential.status == "active",
        email=credential.email,
        mirror=credential.active_mirror,
        status=credential.status,
    )


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
    await db.commit()
    return KmoeStatus(
        connected=True,
        email=credential.email,
        mirror=credential.active_mirror,
        status=credential.status,
    )


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
    try:
        async with client:
            return await search_catalog(client, query=query, page=page)
    except KmoeError as exc:
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
