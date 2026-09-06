from __future__ import annotations

from collections.abc import Iterable

import httpx
from pydantic import BaseModel, ConfigDict, Field


class BangumiSubject(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    name: str = ""
    name_cn: str = ""
    summary: str = ""
    score: float | None = None
    rank: int | None = None
    tags: list[dict[str, object]] = Field(default_factory=list)

    @property
    def display_name(self) -> str:
        return self.name_cn or self.name or f"Bangumi #{self.id}"

    def tag_names(self) -> list[str]:
        names: list[str] = []
        for tag in self.tags:
            name = tag.get("name")
            if isinstance(name, str) and name.strip():
                names.append(name.strip())
        return names


class BangumiMatch(BaseModel):
    subject: BangumiSubject
    source_title: str


class BangumiClient:
    def __init__(
        self,
        *,
        base_url: str = "https://api.bgm.tv",
        timeout: float = 8.0,
        user_agent: str = "kmoeshelf/0.2.0 (+https://github.com/84xiaodu/kmoeshelf)",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout),
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            transport=transport,
        )

    async def __aenter__(self) -> BangumiClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self._client.aclose()

    async def search_books(self, keyword: str, *, limit: int = 5) -> list[BangumiSubject]:
        keyword = keyword.strip()
        if not keyword:
            return []
        response = await self._client.post(
            "/v0/search/subjects",
            params={"limit": max(1, min(limit, 10)), "offset": 0},
            json={
                "keyword": keyword,
                "sort": "match",
                "filter": {"type": [1]},
            },
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        return [BangumiSubject.model_validate(row) for row in rows if isinstance(row, dict)]


async def collect_tag_seeds(
    client: BangumiClient,
    titles: Iterable[str],
    *,
    max_titles: int = 4,
    max_tags: int = 8,
) -> list[BangumiMatch]:
    matches: list[BangumiMatch] = []
    seen_subjects: set[int] = set()
    for title in list(titles)[:max_titles]:
        for subject in await client.search_books(title, limit=3):
            if subject.id in seen_subjects:
                continue
            seen_subjects.add(subject.id)
            matches.append(BangumiMatch(subject=subject, source_title=title))
            break
    matches.sort(
        key=lambda item: (
            item.subject.score is not None,
            item.subject.score or 0,
            -(item.subject.rank or 999999),
        ),
        reverse=True,
    )
    return matches[:max_tags]
