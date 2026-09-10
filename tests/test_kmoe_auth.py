from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from kmoe_subscriptions.kmoe.auth import (
    detect_login_endpoint,
    login,
    parse_account_usage,
    parse_login_response,
)
from kmoe_subscriptions.kmoe.client import KmoeClient
from kmoe_subscriptions.kmoe.errors import InvalidCredentials


FIXTURES = Path(__file__).parent / "fixtures" / "kmoe"


def test_prefers_current_login_endpoint() -> None:
    page = '''
    <form action="/login_do.php"></form>
    <script>fetch("/login_act.php", {method: "POST"})</script>
    '''
    assert detect_login_endpoint(page) == "/login_act.php"


def test_maps_invalid_credentials() -> None:
    with pytest.raises(InvalidCredentials):
        parse_login_response({"msgid": "e400"})


def test_parses_profile_quota_without_inventing_missing_values() -> None:
    usage = parse_account_usage(
        (FIXTURES / "profile_with_quota.html").read_text(encoding="utf-8")
    )

    assert usage is not None
    assert usage.user_level == 2
    assert usage.is_vip is True
    assert usage.free is not None
    assert usage.free.total_mb == 10240
    assert usage.free.used_mb == 2048
    assert usage.free.reset_day == 5
    assert usage.vip is not None
    assert usage.vip.total_mb == 20480
    assert usage.vip.used_mb == 4096
    assert usage.vip.reset_day == 10
    assert parse_account_usage('<a href="/logout.php">out</a>') is None


def test_login_posts_once_and_validates_profile() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path == "/login.php":
            return httpx.Response(
                200,
                request=request,
                text='<script>fetch("/login_act.php")</script>',
            )
        if request.url.path == "/login_act.php":
            return httpx.Response(
                200,
                request=request,
                json={"msgid": "m100"},
                headers={"Set-Cookie": "kmoe_session=fake-session; Path=/"},
            )
        if request.url.path == "/my.php":
            assert request.headers.get("cookie") == "kmoe_session=fake-session"
            return httpx.Response(200, request=request, text='<a href="/logout.php">logout</a>')
        raise AssertionError(request.url)

    async def run() -> None:
        async with KmoeClient(
            ("one.example", "two.example"),
            rate_limit_delay=0,
            transport=httpx.MockTransport(handler),
        ) as client:
            result = await login(client, email="reader@example.com", password="not-stored")
            assert result.mirror == "one.example"
            assert result.cookies == {"kmoe_session": "fake-session"}

    asyncio.run(run())
    assert seen == [
        ("GET", "/login.php"),
        ("POST", "/login_act.php"),
        ("GET", "/my.php"),
    ]
