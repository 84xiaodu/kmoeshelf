from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from .client import DEFAULT_HEADERS, KmoeClient
from .errors import (
    DownloadConnectTimeout,
    DownloadForbidden,
    DownloadRangeInvalid,
    DownloadServerError,
    DownloadUrlExpired,
    DownloadUrlInvalid,
    NonFileResponse,
    QuotaExhausted,
    RateLimited,
    SiteChanged,
)
from .schemas import DownloadFormat


FORMAT_CODES = {DownloadFormat.MOBI: 1, DownloadFormat.EPUB: 2}
QUOTA_MARKERS = ("額度不足", "達到下載額度限制")
TRANSFER_HEADERS = {
    "User-Agent": DEFAULT_HEADERS["User-Agent"],
    "X-Km-From": "kb_http_down",
}


@dataclass(frozen=True, slots=True)
class DownloadInfo:
    url: str


async def get_download_info(
    client: KmoeClient,
    *,
    book_id: str,
    item_id: str,
    download_format: DownloadFormat,
    line: int = 0,
) -> DownloadInfo:
    if not book_id or not item_id or line not in {0, 1}:
        raise ValueError("Download identity or line is invalid")
    response = await client.get(
        "/getdownurl.php",
        params={
            "b": book_id,
            "v": item_id,
            "mobi": FORMAT_CODES[download_format],
            "vip": line,
            "json": 1,
        },
        allow_failover=False,
    )
    try:
        payload = response.json()
    except ValueError as exc:
        if any(marker in response.text for marker in QUOTA_MARKERS):
            raise QuotaExhausted("Kmoe download quota is exhausted") from exc
        raise SiteChanged("Download URL response is not JSON") from exc
    return parse_download_info(payload)


def parse_download_info(payload: Any) -> DownloadInfo:
    if not isinstance(payload, dict):
        raise SiteChanged("Download URL response is not an object")
    message = " ".join(
        str(payload.get(key, "")) for key in ("msg", "message", "msgid")
    )
    if str(payload.get("code", "")) == "e403" or any(
        marker in message for marker in QUOTA_MARKERS
    ):
        raise QuotaExhausted("Kmoe download quota is exhausted")
    if str(payload.get("code", "")) != "200":
        raise SiteChanged("Download URL response has an unknown status")
    url = payload.get("url")
    if not isinstance(url, str):
        raise SiteChanged("Download URL response has no URL")
    validate_download_url(url)
    return DownloadInfo(url=url)


def validate_download_url(url: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.path
        or parsed.path == "/"
    ):
        raise DownloadUrlInvalid("Kmoe returned an unsafe download URL")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith((".localhost", ".local")):
        raise DownloadUrlInvalid("Kmoe returned a local download host")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return
    if not address.is_global:
        raise DownloadUrlInvalid("Kmoe returned a non-public download address")


def raise_for_transfer_status(status: int, *, host: str) -> None:
    if status < 400:
        return
    if status in {401, 404, 410}:
        raise DownloadUrlExpired(
            f"Download URL at {host} expired with HTTP {status}"
        )
    if status == 403:
        raise DownloadForbidden(
            f"Download host {host} rejected the request with HTTP 403"
        )
    if status == 408:
        raise DownloadConnectTimeout(
            f"Download host {host} timed out with HTTP 408"
        )
    if status == 416:
        raise DownloadRangeInvalid(
            f"Download host {host} rejected the resume range with HTTP 416"
        )
    if status == 429:
        raise RateLimited(f"Download host {host} rate limited the request")
    if status >= 500:
        raise DownloadServerError(
            f"Download host {host} failed with HTTP {status}"
        )
    raise DownloadForbidden(
        f"Download host {host} rejected the request with HTTP {status}"
    )


def non_file_response(*, host: str) -> NonFileResponse:
    return NonFileResponse(f"Download host {host} returned non-file content")
