from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from kmoe_subscriptions.kmoe.errors import AuthenticationExpired, SiteChanged
from kmoe_subscriptions.kmoe.parser import parse_volume_data
from kmoe_subscriptions.kmoe.schemas import ContentType


FIXTURES = Path(__file__).parent / "fixtures" / "kmoe"


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_parses_current_volume_indexes_and_types() -> None:
    items = parse_volume_data(load("volume_data_all_types.json"))
    assert [item.content_type for item in items] == [
        ContentType.VOLUME,
        ContentType.EXTRA,
        ContentType.SERIAL,
    ]
    assert items[0].page_count == 121
    assert items[0].mobi_size_mb == Decimal("12.5")
    assert items[0].epub_size_mb == Decimal("10.25")


def test_rejects_unauthenticated_empty_response() -> None:
    with pytest.raises(AuthenticationExpired):
        parse_volume_data(load("volume_data_unauthenticated_empty.json"))


def test_rejects_unknown_type_and_count_mismatch() -> None:
    payload = load("volume_data_all_types.json")
    payload["voldata"][0][3] = "未知"
    with pytest.raises(SiteChanged):
        parse_volume_data(payload)

    payload = load("volume_data_all_types.json")
    payload["volcount"] = 99
    with pytest.raises(SiteChanged):
        parse_volume_data(payload)
