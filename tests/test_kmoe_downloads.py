from __future__ import annotations

import asyncio

import httpx
import pytest

from kmoe_subscriptions.kmoe.client import KmoeClient
from kmoe_subscriptions.kmoe.downloads import (
    TRANSFER_HEADERS,
    get_download_info,
    parse_download_info,
    raise_for_transfer_status,
)
from kmoe_subscriptions.kmoe.errors import (
    DownloadForbidden,
    DownloadServerError,
    DownloadUrlExpired,
    QuotaExhausted,
    RateLimited,
    DownloadUrlInvalid,
)
from kmoe_subscriptions.kmoe.schemas import DownloadFormat


def test_resolves_ephemeral_download_url_with_format_and_line() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/getdownurl.php"
        assert dict(request.url.params) == {
            "b": "50076",
            "v": "v101",
            "mobi": "2",
            "vip": "1",
            "json": "1",
        }
        return httpx.Response(
            200,
            request=request,
            json={
                "code": 200,
                "url": "https://cdn.example.invalid/files/book.epub?signature=fake",
            },
        )

    async def run() -> None:
        async with KmoeClient(
            ("mox.moe",),
            rate_limit_delay=0,
            transport=httpx.MockTransport(handler),
        ) as client:
            result = await get_download_info(
                client,
                book_id="50076",
                item_id="v101",
                download_format=DownloadFormat.EPUB,
                line=1,
            )
            assert result.url.endswith("signature=fake")

    asyncio.run(run())


def test_maps_quota_and_rejects_unsafe_download_hosts() -> None:
    with pytest.raises(QuotaExhausted):
        parse_download_info({"code": "e403", "message": "額度不足"})
    with pytest.raises(DownloadUrlInvalid):
        parse_download_info(
            {"code": 200, "url": "https://127.0.0.1/private/book.epub"}
        )
    with pytest.raises(DownloadUrlInvalid):
        parse_download_info(
            {"code": 200, "url": "http://cdn.example.invalid/book.epub"}
        )


def test_uses_explicit_kmoe_transfer_identity() -> None:
    assert TRANSFER_HEADERS["X-Km-From"] == "kb_http_down"
    assert "python-httpx" not in TRANSFER_HEADERS["User-Agent"]
    assert "KmoeSubscriptions" in TRANSFER_HEADERS["User-Agent"]


def test_maps_safe_transfer_status_errors() -> None:
    with pytest.raises(DownloadForbidden, match=r"cdn\.example\.invalid.*403"):
        raise_for_transfer_status(403, host="cdn.example.invalid")
    with pytest.raises(DownloadUrlExpired):
        raise_for_transfer_status(410, host="cdn.example.invalid")
    with pytest.raises(RateLimited):
        raise_for_transfer_status(429, host="cdn.example.invalid")
    with pytest.raises(DownloadServerError):
        raise_for_transfer_status(503, host="cdn.example.invalid")

    raise_for_transfer_status(200, host="cdn.example.invalid")
