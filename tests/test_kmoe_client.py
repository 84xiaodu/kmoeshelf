from __future__ import annotations

import asyncio

import httpx
import pytest

from kmoe_subscriptions.kmoe.client import KmoeClient
from kmoe_subscriptions.kmoe.errors import (
    AuthenticationExpired,
    MirrorExhausted,
    NetworkError,
    NotFound,
    RateLimited,
)
from kmoe_subscriptions.kmoe.schemas import ContentType, RemoteItem


def test_remote_item_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        RemoteItem(remote_id="", content_type=ContentType.VOLUME, name="Volume 1")


def test_rejects_mirror_paths() -> None:
    with pytest.raises(ValueError):
        KmoeClient(("example.com/path",))


def test_promotes_working_mirror() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        status = 503 if request.url.host == "first.example" else 200
        return httpx.Response(status, request=request, text="ok")

    async def run() -> None:
        async with KmoeClient(
            ("first.example", "second.example"),
            max_retries=1,
            rate_limit_delay=0,
            transport=httpx.MockTransport(handler),
        ) as client:
            response = await client.get("/search.php", params={"keyword": "test"})
            assert response.text == "ok"
            assert client.active_mirror == "second.example"

    asyncio.run(run())
    assert seen == ["first.example", "second.example"]


def test_auth_failure_does_not_try_another_mirror() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        return httpx.Response(401, request=request)

    async def run() -> None:
        async with KmoeClient(
            ("first.example", "second.example"),
            rate_limit_delay=0,
            transport=httpx.MockTransport(handler),
        ) as client:
            with pytest.raises(AuthenticationExpired):
                await client.get("/member.php")

    asyncio.run(run())
    assert seen == ["first.example"]


def test_reports_all_failed_mirrors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    async def run() -> None:
        async with KmoeClient(
            ("one.example", "two.example"),
            max_retries=1,
            rate_limit_delay=0,
            transport=httpx.MockTransport(handler),
        ) as client:
            with pytest.raises(MirrorExhausted) as raised:
                await client.get("/index.php")
            assert raised.value.mirrors == ("one.example", "two.example")

    asyncio.run(run())


def test_does_not_replay_post_across_mirrors() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        raise httpx.ConnectError("ambiguous failure", request=request)

    async def run() -> None:
        async with KmoeClient(
            ("one.example", "two.example"),
            rate_limit_delay=0,
            transport=httpx.MockTransport(handler),
        ) as client:
            with pytest.raises(NetworkError):
                await client.post("/login_act.php", data={"email": "x", "passwd": "y"})

    asyncio.run(run())
    assert seen == ["one.example"]


def test_distinguishes_not_found_and_rate_limit() -> None:
    async def not_found() -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(404, request=request)
        )
        async with KmoeClient(
            ("one.example", "two.example"),
            max_retries=1,
            rate_limit_delay=0,
            transport=transport,
        ) as client:
            with pytest.raises(NotFound):
                await client.get("/c/missing.htm")

    async def rate_limited() -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(429, request=request)
        )
        async with KmoeClient(
            ("one.example", "two.example"),
            rate_limit_delay=0,
            transport=transport,
        ) as client:
            with pytest.raises(RateLimited):
                await client.get("/list.php")

    asyncio.run(not_found())
    asyncio.run(rate_limited())
