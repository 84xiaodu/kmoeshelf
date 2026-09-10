from __future__ import annotations

import httpx

from kmoe_subscriptions.external.bangumi import (
    BangumiClient,
    BangumiCollectionType,
)


def test_bangumi_reads_selected_user_book_collections() -> None:
    requested_types: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer private-token"
        assert request.url.path == "/v0/users/reader/collections"
        assert request.url.params["subject_type"] == "1"
        requested_types.append(request.url.params["type"])
        collection_type = int(request.url.params["type"])
        subject_id = 100 + collection_type
        return httpx.Response(
            200,
            request=request,
            json={
                "data": [
                    {
                        "subject_id": subject_id,
                        "subject_type": 1,
                        "type": collection_type,
                        "rate": 0,
                        "tags": [],
                        "ep_status": 0,
                        "vol_status": 0,
                        "updated_at": "2026-09-10T00:00:00Z",
                        "private": False,
                        "subject": {
                            "id": subject_id,
                            "name": f"Book {subject_id}",
                            "name_cn": f"漫画 {subject_id}",
                            "score": 8.0,
                            "rank": subject_id,
                            "images": {"common": f"https://lain.test/{subject_id}.jpg"},
                        },
                    }
                ]
            },
        )

    async def collect():
        async with BangumiClient(
            base_url="https://bangumi.test",
            access_token="private-token",
            transport=httpx.MockTransport(handler),
        ) as client:
            return await client.user_book_collections(
                "reader",
                [BangumiCollectionType.WISH, BangumiCollectionType.DOING],
            )

    import asyncio

    collections = asyncio.run(collect())

    assert requested_types == ["1", "3"]
    assert [item.collection_type for item in collections] == [
        BangumiCollectionType.WISH,
        BangumiCollectionType.DOING,
    ]
    assert collections[0].subject is not None
    assert collections[0].subject.display_name == "漫画 101"
