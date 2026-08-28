from __future__ import annotations

import asyncio
import re
from urllib.parse import quote

from .client import DEFAULT_MIRRORS, KmoeClient
from .errors import SiteChanged
from .parser import (
    SearchTarget,
    parse_detail_page,
    parse_search_results,
    parse_search_target,
    parse_volume_data,
)
from .schemas import ComicDetails, SearchPage


REMOTE_ID = re.compile(r"^[A-Za-z0-9]+$")


class SearchTargetCache:
    def __init__(self) -> None:
        self._target: SearchTarget | None = None
        self._lock = asyncio.Lock()

    async def resolve(self, client: KmoeClient) -> SearchTarget:
        if self._target is not None:
            return self._target
        async with self._lock:
            if self._target is None:
                discovery = await client.get("/")
                self._target = parse_search_target(
                    discovery.text,
                    origin=f"https://{discovery.url.host}",
                    trusted_hosts=DEFAULT_MIRRORS,
                )
            return self._target

    def invalidate(self) -> None:
        self._target = None


async def search_catalog(
    client: KmoeClient,
    *,
    query: str,
    page: int = 1,
    target_cache: SearchTargetCache | None = None,
) -> SearchPage:
    query = query.strip()
    if not query or page < 1:
        raise ValueError("Search query and page are invalid")
    cache = target_cache or SearchTargetCache()
    target = await cache.resolve(client)
    try:
        client.retarget_mirror(target.host, preserve_cookies=True)
    except ValueError as exc:
        raise SiteChanged("Search form target is not a configured mirror") from exc
    path = target.path
    params: dict[str, str] | None = {target.query_field: query}
    if page > 1:
        encoded = quote(query, safe="")
        path = (
            f"/l/{encoded},all,all,sortpoint,all,all,none/{page}.htm"
        )
        params = None
    response = await client.get(
        path,
        params=params,
        allow_failover=False,
    )
    return parse_search_results(
        response.text,
        query=query,
        requested_page=page,
        origin=f"https://{response.url.host}",
    )


async def get_comic_details(client: KmoeClient, *, remote_id: str) -> ComicDetails:
    if REMOTE_ID.fullmatch(remote_id) is None:
        raise SiteChanged("Comic identity is invalid")
    detail_path = f"/c/{remote_id}.htm"
    response = await client.get(detail_path, allow_failover=False)
    detail = parse_detail_page(
        response.text,
        detail_path=detail_path,
        origin=f"https://{response.url.host}",
    )
    volume_response = await client.get(
        "/data_book.php",
        params={"h": detail.data_hash},
        allow_failover=False,
    )
    try:
        volume_payload = volume_response.json()
    except ValueError as exc:
        raise SiteChanged("Volume response is not JSON") from exc
    return ComicDetails(
        **detail.summary.model_dump(),
        description=detail.description,
        items=parse_volume_data(volume_payload),
    )
