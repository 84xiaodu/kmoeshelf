from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..models import Admin, AdminSession
from ..security import (
    hash_password,
    new_session,
    token_hash,
    utcnow,
    verify_password,
)


SESSION_COOKIE = "kmoe_session"
CSRF_COOKIE = "kmoe_csrf"

router = APIRouter(prefix="/api/auth", tags=["auth"])


class PasswordInput(BaseModel):
    password: str = Field(min_length=12, max_length=1024)


class AuthResult(BaseModel):
    authenticated: bool = True
    csrf_token: str


class AuthStatus(BaseModel):
    setup_required: bool
    authenticated: bool


@dataclass(slots=True)
class CurrentSession:
    row: AdminSession
    raw_token: str


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_db(request: Request):
    async with request.app.state.database.sessions() as session:
        yield session


def require_same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
        raise HTTPException(status_code=403, detail="Cross-origin request rejected")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(status_code=403, detail="Cross-site request rejected")


async def optional_session(
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
    raw_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> CurrentSession | None:
    if not raw_token:
        return None
    row = await db.get(AdminSession, token_hash(settings, raw_token))
    if not row or row.expires_at <= utcnow():
        return None
    return CurrentSession(row=row, raw_token=raw_token)


async def require_session(
    current: Annotated[CurrentSession | None, Depends(optional_session)],
) -> CurrentSession:
    if current is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return current


async def require_csrf(
    current: Annotated[CurrentSession, Depends(require_session)],
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
    csrf_cookie: Annotated[str | None, Cookie(alias=CSRF_COOKIE)] = None,
) -> CurrentSession:
    if not csrf_header or not csrf_cookie:
        raise HTTPException(status_code=403, detail="CSRF token required")
    if not hmac.compare_digest(csrf_header, csrf_cookie) or not hmac.compare_digest(
        csrf_header, current.row.csrf_token
    ):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    return current


def set_session_cookies(
    response: Response, settings: Settings, token: str, csrf_token: str
) -> None:
    max_age = settings.session_hours * 3600
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=max_age,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


async def create_login(
    admin: Admin,
    settings: Settings,
    db: AsyncSession,
    response: Response,
) -> AuthResult:
    created = new_session(settings)
    db.add(
        AdminSession(
            token_hash=created.token_hash,
            admin_id=admin.id,
            csrf_token=created.csrf_token,
            expires_at=created.expires_at,
        )
    )
    await db.commit()
    set_session_cookies(response, settings, created.token, created.csrf_token)
    return AuthResult(csrf_token=created.csrf_token)


@router.get("/status", response_model=AuthStatus)
async def status(
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[CurrentSession | None, Depends(optional_session)],
) -> AuthStatus:
    admin_exists = await db.scalar(select(Admin.id).limit(1)) is not None
    return AuthStatus(
        setup_required=not admin_exists,
        authenticated=current is not None,
    )


@router.post(
    "/setup",
    response_model=AuthResult,
    status_code=201,
    dependencies=[Depends(require_same_origin)],
)
async def setup(
    body: PasswordInput,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AuthResult:
    if await db.scalar(select(Admin.id).limit(1)) is not None:
        raise HTTPException(status_code=409, detail="Administrator already configured")
    admin = Admin(id=1, password_hash=hash_password(body.password))
    db.add(admin)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="Administrator already configured"
        ) from exc
    return await create_login(admin, settings, db, response)


@router.post(
    "/login",
    response_model=AuthResult,
    dependencies=[Depends(require_same_origin)],
)
async def login(
    body: PasswordInput,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AuthResult:
    admin = await db.get(Admin, 1)
    if admin is None:
        raise HTTPException(status_code=409, detail="Administrator setup required")
    if not verify_password(admin.password_hash, body.password):
        raise HTTPException(status_code=401, detail="Invalid password")
    return await create_login(admin, settings, db, response)


@router.get("/me", response_model=AuthResult)
async def me(
    current: Annotated[CurrentSession, Depends(require_session)],
) -> AuthResult:
    return AuthResult(csrf_token=current.row.csrf_token)


@router.post(
    "/logout",
    status_code=204,
    dependencies=[Depends(require_same_origin)],
)
async def logout(
    response: Response,
    current: Annotated[CurrentSession, Depends(require_csrf)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    await db.execute(
        delete(AdminSession).where(AdminSession.token_hash == current.row.token_hash)
    )
    await db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    response.status_code = 204
    return response

