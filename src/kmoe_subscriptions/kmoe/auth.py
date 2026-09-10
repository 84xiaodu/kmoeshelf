from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any

from .client import KmoeClient
from .errors import (
    AccountDisabled,
    AuthenticationChallenge,
    AuthenticationExpired,
    InvalidCredentials,
    SiteChanged,
)
from .schemas import KmoeAccountUsage, QuotaUsage


CURRENT_LOGIN = re.compile(r"['\"](/login_act\.php)['\"]")
LEGACY_LOGIN = re.compile(r"<form[^>]+action=['\"](/login_do\.php)['\"]", re.I)
PROFILE_SENTINELS = ("/logout.php", "登出", "退出登入")
PROFILE_VARIABLE = re.compile(
    r"\bvar\s+(is_vip|user_level)\s*=\s*['\"]?(\d+)['\"]?\s*;?",
    re.I,
)
USER_RESET = re.compile(r"Lv\d+\s*額度\s*[:：]\s*每月\s*(\d+)\s*日", re.I)
USER_TOTAL = re.compile(r"Lv\d+\s*每月額度\s*[:：]\s*([\d.]+)\s*M", re.I)
USER_USED = re.compile(r"本月已用免費額度\s*[:：]\s*([\d.]+)\s*M", re.I)
VIP_RESET = re.compile(r"VIP\s*額度\s*[:：]\s*每月\s*(\d+)\s*日", re.I)
VIP_TOTAL = re.compile(r"VIP\s*每月額度\s*[:：]\s*([\d.]+)\s*M", re.I)
VIP_USED = re.compile(r"本月已經用VIP額度\s*[:：]\s*([\d.]+)\s*M", re.I)


class _ProfileTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


@dataclass(frozen=True, slots=True)
class LoginSession:
    mirror: str
    cookies: dict[str, str]
    usage: KmoeAccountUsage | None = None


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
    usage = await validate_session(client)
    return LoginSession(
        mirror=client.active_mirror,
        cookies=client.get_cookies(),
        usage=usage,
    )


def _decimal(pattern: re.Pattern[str], text: str) -> Decimal | None:
    match = pattern.search(text)
    if match is None:
        return None
    try:
        return Decimal(match.group(1))
    except InvalidOperation:
        return None


def _integer(pattern: re.Pattern[str], text: str) -> int | None:
    match = pattern.search(text)
    return int(match.group(1)) if match is not None else None


def parse_account_usage(page: str) -> KmoeAccountUsage | None:
    parser = _ProfileTextParser()
    parser.feed(page)
    text = " ".join(part.strip() for part in parser.parts if part.strip())
    variables = {
        name.lower(): int(value) for name, value in PROFILE_VARIABLE.findall(page)
    }
    free_values = (
        _decimal(USER_TOTAL, text),
        _decimal(USER_USED, text),
        _integer(USER_RESET, text),
    )
    vip_values = (
        _decimal(VIP_TOTAL, text),
        _decimal(VIP_USED, text),
        _integer(VIP_RESET, text),
    )
    if not variables and not any(value is not None for value in (*free_values, *vip_values)):
        return None
    free = (
        QuotaUsage(
            total_mb=free_values[0],
            used_mb=free_values[1],
            reset_day=free_values[2],
        )
        if any(value is not None for value in free_values)
        else None
    )
    vip = (
        QuotaUsage(
            total_mb=vip_values[0],
            used_mb=vip_values[1],
            reset_day=vip_values[2],
        )
        if any(value is not None for value in vip_values)
        else None
    )
    raw_vip = variables.get("is_vip")
    return KmoeAccountUsage(
        user_level=variables.get("user_level"),
        is_vip=bool(raw_vip) if raw_vip is not None else vip is not None,
        free=free,
        vip=vip,
    )


async def validate_session(client: KmoeClient) -> KmoeAccountUsage | None:
    response = await client.get("/my.php", allow_failover=False)
    if response.url.path.endswith("/login.php"):
        raise AuthenticationExpired("Kmoe session redirected to login")
    if not any(sentinel in response.text for sentinel in PROFILE_SENTINELS):
        raise SiteChanged("Kmoe profile page has no authenticated sentinel")
    return parse_account_usage(response.text)

