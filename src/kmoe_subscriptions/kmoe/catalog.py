from __future__ import annotations

import re
from urllib.parse import quote

from .client import KmoeClient
from .errors import SiteChanged
from .parser import parse_detail_page, parse_search_results, parse_volume_data
from .schemas import ComicDetails, SearchPage


REMOTE_ID = re.compile(r"^[A-Za-z0-9]+$")


async def search_catalog(
    client: KmoeClient, *, query: str, page: int = 1
) -> SearchPage:
    query = query.strip()
    if not query or page < 1:
        raise ValueError("Search query and page are invalid")
    path = f"/l/{quote(query, safe='')},all,all,sortpoint,all,all,none/{page}.htm"
    response = await client.get(path)
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
