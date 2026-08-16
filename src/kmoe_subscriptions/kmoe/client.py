from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable
from types import TracebackType

import httpx

from .errors import (
    AuthenticationExpired,
    MirrorExhausted,
    NetworkError,
    NotFound,
    RateLimited,
)


DEFAULT_MIRRORS = ("mox.moe", "kxo.moe", "kxx.moe", "kzz.moe", "koz.moe")
FAILOVER_STATUSES = frozenset({404, 502, 503, 504})
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; KmoeSubscriptions/0.1)",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
}


class KmoeClient:
    def __init__(
        self,
        mirrors: Iterable[str] = DEFAULT_MIRRORS,
        *,
        max_retries: int = 3,
        rate_limit_delay: float = 0.25,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        cleaned = tuple(
            dict.fromkeys(m.removeprefix("https://").rstrip("/") for m in mirrors)
        )
        if not cleaned:
            raise ValueError("At least one Kmoe mirror is required")
        if any(not mirror or "/" in mirror or ":" in mirror for mirror in cleaned):
            raise ValueError("Kmoe mirrors must be HTTPS hostnames without paths")
        if max_retries < 1:
            raise ValueError("max_retries must be at least 1")
        if rate_limit_delay < 0:
            raise ValueError("rate_limit_delay cannot be negative")
        self._mirrors = cleaned
        self.active_mirror = cleaned[0]
        self.max_retries = max_retries
        self.rate_limit_delay = rate_limit_delay
        self._last_request_at = 0.0
        self._rate_lock = asyncio.Lock()
        self._client = httpx.AsyncClient(
            headers=DEFAULT_HEADERS,
            follow_redirects=True,
            timeout=httpx.Timeout(30),
            transport=transport,
        )

    async def __aenter__(self) -> KmoeClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    def set_cookies(self, cookies: dict[str, str]) -> None:
        self._client.cookies.clear()
        for name, value in cookies.items():
            self._client.cookies.set(name, value)

    def get_cookies(self) -> dict[str, str]:
        return dict(self._client.cookies.items())

    async def get(self, path: str, **kwargs: object) -> httpx.Response:
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: object) -> httpx.Response:
        return await self.request("POST", path, **kwargs)

    async def request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        if not path.startswith("/"):
            raise ValueError("Kmoe request path must start with '/'")

        can_replay = method.upper() in {"GET", "HEAD"}
        mirrors = (self.active_mirror,)
        if can_replay:
            mirrors += tuple(
                mirror for mirror in self._mirrors if mirror != self.active_mirror
            )
        failed: list[str] = []
        not_found = 0

        for mirror in mirrors:
            url = f"https://{mirror}{path}"
            attempts = self.max_retries if can_replay else 1
            for attempt in range(attempts):
                try:
                    await self._rate_limit()
                    response = await self._client.request(method, url, **kwargs)
                except (httpx.ConnectError, httpx.TimeoutException):
                    if attempt + 1 < attempts:
                        await asyncio.sleep(0.25 * (2**attempt))
                        continue
                    if not can_replay:
                        raise NetworkError("Non-idempotent Kmoe request failed; not replayed")
                    break
                except httpx.RequestError as exc:
                    if can_replay:
                        break
                    raise NetworkError(str(exc)) from exc

                if response.status_code in {401, 403}:
                    raise AuthenticationExpired("Kmoe session is not authenticated")
                if response.status_code == 429:
                    raise RateLimited("Kmoe rate limit reached")
                if response.status_code in FAILOVER_STATUSES and can_replay:
                    if response.status_code == 404:
                        not_found += 1
                    break
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise NetworkError(f"Kmoe returned HTTP {response.status_code}") from exc
                self.active_mirror = mirror
                return response
            failed.append(mirror)

        if not_found == len(failed):
            raise NotFound(f"Kmoe resource not found on {len(failed)} mirrors")
        raise MirrorExhausted(tuple(failed))

    async def _rate_limit(self) -> None:
        async with self._rate_lock:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < self.rate_limit_delay:
                await asyncio.sleep(self.rate_limit_delay - elapsed)
            self._last_request_at = time.monotonic()
