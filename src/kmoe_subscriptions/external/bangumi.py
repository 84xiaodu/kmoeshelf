from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict


class BangumiImages(BaseModel):
    model_config = ConfigDict(extra="ignore")

    small: str | None = None
    grid: str | None = None
    large: str | None = None
    medium: str | None = None
    common: str | None = None


class BangumiSubject(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    name: str = ""
    name_cn: str = ""
    summary: str = ""
    platform: str | None = None
    date: str | None = None
    images: BangumiImages | None = None
    nsfw: bool = False

    @property
    def display_name(self) -> str:
        return self.name_cn or self.name or f"Bangumi #{self.id}"

    @property
    def cover_url(self) -> str | None:
        if self.images is None:
            return None
        return self.images.common or self.images.medium or self.images.large


class BangumiCollectionType(StrEnum):
    WISH = "wish"
    COLLECT = "collect"
    DOING = "doing"
    ON_HOLD = "on_hold"
    DROPPED = "dropped"

    @property
    def api_value(self) -> int:
        return {
            self.WISH: 1,
            self.COLLECT: 2,
            self.DOING: 3,
            self.ON_HOLD: 4,
            self.DROPPED: 5,
        }[self]


class BangumiUserCollection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    subject_id: int
    type: int
    subject: BangumiSubject | None = None

    @property
    def collection_type(self) -> BangumiCollectionType:
        return {
            1: BangumiCollectionType.WISH,
            2: BangumiCollectionType.COLLECT,
            3: BangumiCollectionType.DOING,
            4: BangumiCollectionType.ON_HOLD,
            5: BangumiCollectionType.DROPPED,
        }[self.type]


class BangumiClient:
    def __init__(
        self,
        *,
        base_url: str = "https://api.bgm.tv",
        timeout: float = 8.0,
        user_agent: str = "kmoeshelf/0.3.0 (+https://github.com/84xiaodu/kmoeshelf)",
        access_token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        headers = {"User-Agent": user_agent, "Accept": "application/json"}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout),
            headers=headers,
            transport=transport,
        )

    async def __aenter__(self) -> BangumiClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self._client.aclose()

    async def user_book_collections(
        self,
        username: str,
        collection_types: Iterable[BangumiCollectionType],
    ) -> list[BangumiUserCollection]:
        username = username.strip()
        if not username:
            raise ValueError("Bangumi username is required")
        results: dict[int, BangumiUserCollection] = {}
        for collection_type in dict.fromkeys(collection_types):
            offset = 0
            for _ in range(10):
                response = await self._client.get(
                    f"/v0/users/{quote(username, safe='')}/collections",
                    params={
                        "subject_type": 1,
                        "type": collection_type.api_value,
                        "limit": 50,
                        "offset": offset,
                    },
                )
                response.raise_for_status()
                payload = response.json()
                rows = payload.get("data", []) if isinstance(payload, dict) else []
                parsed = [
                    BangumiUserCollection.model_validate(row)
                    for row in rows
                    if isinstance(row, dict)
                ]
                for item in parsed:
                    if item.subject is not None and not item.subject.nsfw:
                        results[item.subject_id] = item
                if len(rows) < 50:
                    break
                offset += 50
        return sorted(
            results.values(),
            key=lambda item: (
                item.collection_type.api_value,
                (item.subject.display_name if item.subject else ""),
            ),
        )
