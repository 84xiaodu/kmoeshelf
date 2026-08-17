from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from kmoe_subscriptions.kmoe.errors import AuthenticationExpired, SiteChanged
from kmoe_subscriptions.kmoe.parser import (
    parse_detail_page,
    parse_search_target,
    parse_search_results,
    parse_volume_data,
)
from kmoe_subscriptions.kmoe.schemas import ContentType


FIXTURES = Path(__file__).parent / "fixtures" / "kmoe"
TRUSTED_MIRRORS = ("mox.moe", "kxo.moe", "kxx.moe")


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parses_current_search_contract_declarations_and_concatenated_values() -> None:
    result = parse_search_results(
        load_text("search_results_current.html"),
        query="示例",
        requested_page=1,
        origin="https://mox.moe",
    )
    assert result.current_page == 1
    assert result.total_pages == 2
    assert [comic.remote_id for comic in result.results] == ["50076", "A12"]
    assert result.results[0].title == "示例漫画"
    assert result.results[0].author == "作者 & 甲"
    assert result.results[0].language == "ja"
    assert result.results[1].detail_path == "/c/A12.htm"
    assert result.results[1].title == 'Rock "N" Roll'
    assert result.results[1].author == "Author 乙"


def test_discovers_current_trusted_search_target() -> None:
    target = parse_search_target(
        load_text("search_form_current.html"),
        origin="https://mox.moe",
        trusted_hosts=TRUSTED_MIRRORS,
    )
    assert target.host == "kxx.moe"
    assert target.path == "/list.php"
    assert target.query_field == "s"


@pytest.mark.parametrize(
    "form",
    [
        '<form action="http://kxx.moe/list.php"><input name="s"></form>',
        '<form action="https://attacker.example/list.php"><input name="s"></form>',
        '<form action="https://kxx.moe/other.php"><input name="s"></form>',
        '<form action="https://kxx.moe/list.php" method="post"><input name="s"></form>',
        '<form action="https://kxx.moe/list.php"><input name="q"></form>',
    ],
)
def test_rejects_untrusted_search_forms(form: str) -> None:
    with pytest.raises(SiteChanged, match="search form"):
        parse_search_target(
            form,
            origin="https://mox.moe",
            trusted_hosts=TRUSTED_MIRRORS,
        )


def test_rejects_conflicting_search_targets() -> None:
    page = """
    <form action="https://kxx.moe/list.php"><input name="s"></form>
    <form action="https://kxo.moe/list.php"><input name="s"></form>
    """
    with pytest.raises(SiteChanged, match="conflicting"):
        parse_search_target(
            page,
            origin="https://mox.moe",
            trusted_hosts=TRUSTED_MIRRORS,
        )


def test_distinguishes_valid_empty_search_from_site_change() -> None:
    result = parse_search_results(
        load_text("search_empty_valid.html"),
        query="missing",
        requested_page=1,
        origin="https://mox.moe",
    )
    assert result.results == ()

    with pytest.raises(SiteChanged):
        parse_search_results(
            load_text("search_site_changed.html"),
            query="missing",
            requested_page=1,
            origin="https://mox.moe",
        )


def test_normalizes_current_zero_page_empty_search() -> None:
    result = parse_search_results(
        load_text("search_empty_zero_pages.html"),
        query="missing",
        requested_page=1,
        origin="https://kxx.moe",
    )
    assert result.current_page == 1
    assert result.total_pages == 1
    assert result.results == ()

    with pytest.raises(SiteChanged, match="total pages"):
        parse_search_results(
            load_text("search_empty_zero_pages.html"),
            query="missing",
            requested_page=2,
            origin="https://kxx.moe",
        )


def test_rejects_dynamic_javascript_operands_in_search_results() -> None:
    page = """
    <script>
    disp_divinfo('result-' + window.remoteId, '/c/50076.htm', '/cover.jpg', '',
                 '', 'not-en', 'not-end', 'not-break', '9', 'Title', 'Author');
    disp_divpage('pages', 'query', '1');
    var page_now = '1';
    </script>
    """
    with pytest.raises(SiteChanged, match="unsupported operand"):
        parse_search_results(
            page,
            query="query",
            requested_page=1,
            origin="https://mox.moe",
        )


def test_parses_current_detail_and_sanitizes_description() -> None:
    detail = parse_detail_page(
        load_text("comic_detail_current.html"),
        detail_path="/c/50076.htm",
        origin="https://mox.moe",
    )
    assert detail.summary.remote_id == "50076"
    assert detail.summary.title == "示例 & 漫画"
    assert detail.summary.author == "作者甲, 作者乙"
    assert detail.summary.language == "繁體中文"
    assert detail.summary.cover_url == "https://mox.moe/covers/50076.jpg"
    assert detail.description == "第一行第二行 & 安全"
    assert detail.data_hash == "opaque_test_hash"


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
