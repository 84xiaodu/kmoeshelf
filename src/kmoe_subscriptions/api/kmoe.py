from __future__ import annotations

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import get_db, get_settings, require_csrf, require_same_origin, require_session
from ..config import Settings
from ..external.bangumi import collect_tag_seeds
from ..kmoe.auth import login
from ..kmoe.catalog import SearchTargetCache, get_comic_details, search_catalog
from ..kmoe.client import DEFAULT_MIRRORS, KmoeClient
from ..kmoe.credentials import decrypt_cookies, encrypt_cookies
from ..kmoe.errors import AuthenticationExpired, KmoeError
from ..kmoe.schemas import ComicDetails, ComicSummary, SearchPage
from ..models import AppSetting, Comic, KmoeCredential, Subscription
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


class RecommendationSection(BaseModel):
    title: str
    reason: str
    query: str
    results: tuple[ComicSummary, ...] = ()


class RecommendationPage(BaseModel):
    sections: tuple[RecommendationSection, ...] = ()


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
    "/recommendations",
    response_model=RecommendationPage,
    dependencies=[Depends(require_session)],
)
async def recommendations(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
    section_limit: Annotated[int, Query(ge=1, le=4)] = 3,
    per_section: Annotated[int, Query(ge=1, le=12)] = 6,
) -> RecommendationPage:
    client, credential = await saved_client(request, settings, db)
    target_cache: SearchTargetCache = request.app.state.search_target_cache
    subscribed_rows = await db.execute(
        select(Comic.remote_id, Comic.title, Comic.author)
        .join(Subscription, Subscription.comic_id == Comic.id)
        .order_by(Subscription.id.desc())
    )
    excluded: set[str] = set()
    title_seeds: list[str] = []
    author_seeds: list[str] = []
    for remote_id, title, author in subscribed_rows:
        excluded.add(remote_id)
        if title and title not in title_seeds:
            title_seeds.append(title)
        if author and author not in author_seeds:
            author_seeds.append(author)

    seed_specs = []
    if settings.bangumi_recommendations and title_seeds:
        try:
            bangumi_factory = request.app.state.bangumi_client_factory
            async with bangumi_factory() as bangumi:
                for match in await collect_tag_seeds(bangumi, title_seeds):
                    for tag in match.subject.tag_names()[:3]:
                        if len(tag) < 2 or tag in {"漫画", "コミック"}:
                            continue
                        seed_specs.append(
                            (
                                tag,
                                f"Bangumi：{tag}",
                                f"根据你订阅的《{match.source_title}》在 Bangumi 上匹配到的标签",
                            )
                        )
        except Exception:
            seed_specs = []

    seed_specs.extend(
        (author, "同作者作品", f"你已订阅过 {author} 的作品")
        for author in author_seeds[:2]
    )
    seed_specs.extend(
        [
            ("異世界", "异世界题材", "适合想找轻松冒险与转生题材时浏览"),
            ("戀愛", "恋爱与日常", "从恋爱、校园和日常关键词中挑选"),
            ("懸疑", "悬疑与剧情", "偏剧情向作品的发现入口"),
            ("完結", "完结作品", "适合一次性补完的书单入口"),
        ]
    )

    sections: list[RecommendationSection] = []
    seen_queries: set[str] = set()
    seen_results: set[str] = set(excluded)
    try:
        async with client:
            for query, title, reason in seed_specs:
                if query in seen_queries:
                    continue
                seen_queries.add(query)
                page = await search_catalog(
                    client,
                    query=query,
                    page=1,
                    target_cache=target_cache,
                )
                results = []
                for comic in page.results:
                    if comic.remote_id in seen_results:
                        continue
                    seen_results.add(comic.remote_id)
                    results.append(comic)
                    if len(results) >= per_section:
                        break
                if results:
                    sections.append(
                        RecommendationSection(
                            title=title,
                            reason=reason,
                            query=query,
                            results=tuple(results),
                        )
                    )
                if len(sections) >= section_limit:
                    break
    except KmoeError as exc:
        target_cache.invalidate()
        await raise_kmoe_error(exc, db=db, credential=credential)

    return RecommendationPage(sections=tuple(sections))


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
