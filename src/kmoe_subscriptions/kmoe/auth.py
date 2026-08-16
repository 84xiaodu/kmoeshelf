from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .client import KmoeClient
from .errors import (
    AccountDisabled,
    AuthenticationChallenge,
    AuthenticationExpired,
    InvalidCredentials,
    SiteChanged,
)


CURRENT_LOGIN = re.compile(r"['\"](/login_act\.php)['\"]")
LEGACY_LOGIN = re.compile(r"<form[^>]+action=['\"](/login_do\.php)['\"]", re.I)
PROFILE_SENTINELS = ("/logout.php", "登出", "退出登入")


@dataclass(frozen=True, slots=True)
class LoginSession:
    mirror: str
    cookies: dict[str, str]


def detect_login_endpoint(page: str) -> str:
    current = CURRENT_LOGIN.search(page)
    if current:
        return current.group(1)
    legacy = LEGACY_LOGIN.search(page)
    if legacy:
        return legacy.group(1)
    raise SiteChanged("Login page exposes no supported endpoint")


def parse_login_response(payload: Any) -> None:
    if not isinstance(payload, dict) or not isinstance(payload.get("msgid"), str):
        raise SiteChanged("Login response is not recognized JSON")
    code = payload["msgid"]
    if code == "m100":
        return
    if code == "e400":
        raise InvalidCredentials("Kmoe email or password is incorrect")
    if code == "e402":
        raise AccountDisabled("Kmoe account is disabled")
    if code in {"e401", "e403"}:
        raise AuthenticationChallenge("Kmoe login challenge must be refreshed")
    raise SiteChanged(f"Unknown Kmoe login response code: {code}")


async def login(client: KmoeClient, *, email: str, password: str) -> LoginSession:
    login_page = await client.get("/login.php")
    endpoint = detect_login_endpoint(login_page.text)
    response = await client.post(
        endpoint,
        data={"email": email, "passwd": password},
        headers={"Referer": f"https://{client.active_mirror}/login.php"},
    )
    try:
        payload = response.json()
    except ValueError as exc:
        raise SiteChanged("Login response is not JSON") from exc
    parse_login_response(payload)
    if not client.get_cookies():
        raise AuthenticationExpired("Kmoe login returned no session cookie")
    await validate_session(client)
    return LoginSession(mirror=client.active_mirror, cookies=client.get_cookies())


async def validate_session(client: KmoeClient) -> None:
    response = await client.get("/my.php", allow_failover=False)
    if response.url.path.endswith("/login.php"):
        raise AuthenticationExpired("Kmoe session redirected to login")
    if not any(sentinel in response.text for sentinel in PROFILE_SENTINELS):
        raise SiteChanged("Kmoe profile page has no authenticated sentinel")

