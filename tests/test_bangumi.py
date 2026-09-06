from __future__ import annotations

import httpx

from kmoe_subscriptions.external.bangumi import BangumiClient, collect_tag_seeds


async def _collect(transport: httpx.MockTransport):
    async with BangumiClient(
        base_url="https://bangumi.test",
        transport=transport,
    ) as client:
        return await collect_tag_seeds(client, ["示例漫画"])


def test_bangumi_collects_tags_from_book_search() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v0/search/subjects"
        assert request.url.params["limit"] == "3"
        assert request.headers["user-agent"].startswith("kmoeshelf/")
        return httpx.Response(
            200,
            request=request,
            json={
                "data": [
                    {
                        "id": 42,
                        "name": "Example",
                        "name_cn": "示例漫画",
                        "score": 7.8,
                        "rank": 1200,
                        "tags": [{"name": "百合", "count": 12}, {"name": "校园"}],
                    }
                ]
            },
        )

    import asyncio

    matches = asyncio.run(_collect(httpx.MockTransport(handler)))

    assert matches[0].source_title == "示例漫画"
    assert matches[0].subject.display_name == "示例漫画"
    assert matches[0].subject.tag_names() == ["百合", "校园"]
