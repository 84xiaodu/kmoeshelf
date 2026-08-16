from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from .errors import AuthenticationExpired, SiteChanged
from .schemas import ContentType, RemoteItem


CONTENT_TYPES = {
    "單行本": ContentType.VOLUME,
    "番外篇": ContentType.EXTRA,
    "話": ContentType.SERIAL,
}


def parse_volume_data(payload: Any) -> tuple[RemoteItem, ...]:
    if not isinstance(payload, dict):
        raise SiteChanged("Volume response is not an object")
    rows = payload.get("voldata")
    if not isinstance(rows, list):
        raise SiteChanged("Volume response has no voldata list")
    count = _integer(payload.get("volcount"), "volcount")
    if count != len(rows):
        raise SiteChanged("Volume count does not match voldata")
    if not rows:
        if str(payload.get("msgid", "")) in {"", "0"} or not str(
            payload.get("bookname", "")
        ).strip():
            raise AuthenticationExpired("Unauthenticated empty volume response")
        raise SiteChanged("Authenticated empty-volume contract is not yet verified")

    parsed: list[RemoteItem] = []
    for index, row in enumerate(rows):
        if not isinstance(row, list) or len(row) < 12:
            raise SiteChanged(f"Volume row {index} is too short")
        remote_id = str(row[0]).strip()
        name = str(row[5]).strip()
        if not remote_id or not name:
            raise SiteChanged(f"Volume row {index} has no identity")
        try:
            content_type = CONTENT_TYPES[str(row[3]).strip()]
        except KeyError as exc:
            raise SiteChanged(f"Unknown volume type in row {index}") from exc
        parsed.append(
            RemoteItem(
                remote_id=remote_id,
                content_type=content_type,
                name=name,
                sort_order=_integer(row[4], f"voldata[{index}][4]"),
                page_count=_integer(row[7], f"voldata[{index}][7]"),
                mobi_size_mb=_decimal(row[9], f"voldata[{index}][9]"),
                epub_size_mb=_decimal(row[11], f"voldata[{index}][11]"),
            )
        )
    return tuple(parsed)


def _integer(value: Any, field: str) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise SiteChanged(f"{field} is not an integer") from exc
    if parsed < 0:
        raise SiteChanged(f"{field} cannot be negative")
    return parsed


def _decimal(value: Any, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise SiteChanged(f"{field} is not numeric") from exc
    if parsed < 0:
        raise SiteChanged(f"{field} cannot be negative")
    return parsed

