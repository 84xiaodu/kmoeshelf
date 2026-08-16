from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_db, get_settings, require_csrf, require_same_origin, require_session
from ..config import Settings
from ..kmoe.auth import login
from ..kmoe.client import KmoeClient
from ..kmoe.credentials import encrypt_cookies
from ..kmoe.errors import KmoeError
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
    return 502


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
        raise HTTPException(
            status_code=error_status(exc.code),
            detail={"code": exc.code, "message": str(exc)},
        ) from exc

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
