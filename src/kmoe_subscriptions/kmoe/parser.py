from __future__ import annotations

import html
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any, Iterator
from urllib.parse import urljoin, urlsplit

from .errors import AuthenticationExpired, SiteChanged
from .schemas import ComicSummary, ContentType, RemoteItem, SearchPage


CONTENT_TYPES = {
    "單行本": ContentType.VOLUME,
    "番外篇": ContentType.EXTRA,
    "話": ContentType.SERIAL,
}
DETAIL_PATH = re.compile(r"^/(?:m/)?c/([A-Za-z0-9]+)\.htm$")
PAGE_NOW = re.compile(r"\bvar\s+page_now\s*=\s*(['\"])(\d+)\1")
DESCRIPTION_ASSIGNMENT = re.compile(r"div_desc_content[^;]*?\.innerHTML\s*=\s*", re.I)
LANGUAGE = re.compile(r"語言\s*[：:]\s*([^\s|/]+)")
VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
JAVASCRIPT_ESCAPES = {
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "b": "\b",
    "f": "\f",
    "v": "\v",
}


@dataclass(frozen=True, slots=True)
class DetailPage:
    summary: ComicSummary
    description: str | None
    data_hash: str


@dataclass(frozen=True, slots=True)
class SearchTarget:
    host: str
    path: str = "/list.php"
    query_field: str = "s"


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


class _SearchFormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.forms: list[tuple[str, str, frozenset[str]]] = []
        self._action: str | None = None
        self._method = "get"
        self._names: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name.lower(): value or "" for name, value in attrs}
        if tag == "form":
            if self._action is not None:
                raise SiteChanged("Search page has nested search forms")
            self._action = attributes.get("action", "")
            self._method = attributes.get("method", "get").strip().lower()
            self._names = set()
        elif self._action is not None and tag in {"input", "select"}:
            name = attributes.get("name", "").strip()
            if name:
                self._names.add(name)

    def handle_endtag(self, tag: str) -> None:
        if tag == "form" and self._action is not None:
            self.forms.append(
                (self._action, self._method, frozenset(self._names))
            )
            self._action = None
            self._method = "get"
            self._names = set()


class _DetailParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.book_id: str | None = None
        self.cover_url: str | None = None
        self.title_parts: list[str] = []
        self.document_title_parts: list[str] = []
        self.author_parts: list[str] = []
        self.author_links: list[str] = []
        self._title_depth: int | None = None
        self._document_title_depth: int | None = None
        self._author_depth: int | None = None
        self._author_link_depth: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name.lower(): value or "" for name, value in attrs}
        classes = set(attributes.get("class", "").split())
        depth = len(self.stack) + 1
        if tag == "input" and attributes.get("name") == "bookid":
            self.book_id = attributes.get("value", "").strip() or self.book_id
        if tag == "meta" and attributes.get("name", "").lower() == "og:image":
            self.cover_url = attributes.get("content", "").strip() or self.cover_url
        if tag == "img" and "img_book" in classes:
            self.cover_url = attributes.get("src", "").strip() or self.cover_url
        if tag == "font" and "text_bglight_big" in classes:
            self._title_depth = depth
        if tag == "title":
            self._document_title_depth = depth
        if tag == "td" and "author" in classes:
            self._author_depth = depth
        if tag == "a" and self._author_depth is not None:
            self._author_link_depth = depth
        if tag not in VOID_TAGS:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        depth = len(self.stack)
        if self._title_depth == depth:
            self._title_depth = None
        if self._document_title_depth == depth:
            self._document_title_depth = None
        if self._author_link_depth == depth:
            self._author_link_depth = None
        if self._author_depth == depth:
            self._author_depth = None
        if self.stack:
            self.stack.pop()

    def handle_data(self, data: str) -> None:
        if self._title_depth is not None:
            self.title_parts.append(data)
        if self._document_title_depth is not None:
            self.document_title_parts.append(data)
        if self._author_depth is not None:
            self.author_parts.append(data)
        if self._author_link_depth is not None:
            self.author_links.append(data)


def parse_search_results(
    page: str,
    *,
    query: str,
    requested_page: int,
    origin: str,
) -> SearchPage:
    result_calls = [
        arguments
        for arguments in _javascript_calls(page, "disp_divinfo")
        if arguments
    ]
    page_calls = [
        arguments
        for arguments in _javascript_calls(page, "disp_divpage")
        if arguments
    ]
    if not result_calls and not page_calls:
        raise SiteChanged("Search page has no recognized result structure")
    current_match = PAGE_NOW.search(page)
    if current_match is None:
        raise SiteChanged("Search page has no current-page marker")
    current_page = _integer(current_match.group(2), "page_now")
    if current_page < 1:
        raise SiteChanged("Search current page must be positive")
    total_pages = 1
    if page_calls:
        arguments = page_calls[0]
        if len(arguments) < 3:
            raise SiteChanged("Search pagination call is too short")
        total_pages = _integer(arguments[2], "total_pages")
        if total_pages == 0:
            if result_calls or requested_page != 1 or current_page != 1:
                raise SiteChanged("Search total pages do not match an empty result")
            total_pages = 1
        elif total_pages < 1:
            raise SiteChanged("Search total pages must be positive")
    if current_page != requested_page or current_page > total_pages:
        raise SiteChanged("Search pagination does not match the request")

    summaries: list[ComicSummary] = []
    seen: set[str] = set()
    for index, arguments in enumerate(result_calls):
        if len(arguments) < 11:
            raise SiteChanged(f"Search result {index} is too short")
        detail_path, remote_id = normalize_detail_path(arguments[1], origin=origin)
        if remote_id in seen:
            continue
        seen.add(remote_id)
        title = _plain_text(arguments[9])
        if not title:
            raise SiteChanged(f"Search result {index} has no title")
        author = _plain_text(arguments[10]) or None
        language = "ja" if arguments[4] == "" else (
            "en" if arguments[5] == "" else None
        )
        summaries.append(
            ComicSummary(
                remote_id=remote_id,
                title=title,
                author=author,
                language=language,
                detail_path=detail_path,
                cover_url=_normalize_url(arguments[2], origin=origin),
            )
        )
    return SearchPage(
        query=query,
        current_page=current_page,
        total_pages=total_pages,
        results=tuple(summaries),
    )


def parse_search_target(
    page: str,
    *,
    origin: str,
    trusted_hosts: tuple[str, ...],
) -> SearchTarget:
    document = _SearchFormParser()
    document.feed(page)
    trusted = {host.lower() for host in trusted_hosts}
    targets: set[SearchTarget] = set()
    for action, method, names in document.forms:
        if method != "get" or "s" not in names:
            continue
        try:
            parsed = urlsplit(urljoin(origin, html.unescape(action.strip())))
            port = parsed.port
        except ValueError:
            continue
        host = (parsed.hostname or "").lower()
        if (
            parsed.scheme != "https"
            or host not in trusted
            or parsed.username is not None
            or parsed.password is not None
            or port is not None
            or parsed.path != "/list.php"
            or parsed.query
            or parsed.fragment
        ):
            continue
        targets.add(SearchTarget(host=host))
    if not targets:
        raise SiteChanged("Search page has no trusted search form")
    if len(targets) != 1:
        raise SiteChanged("Search page has conflicting search form targets")
    return targets.pop()


def parse_detail_page(page: str, *, detail_path: str, origin: str) -> DetailPage:
    normalized_path, path_id = normalize_detail_path(detail_path, origin=origin)
    document = _DetailParser()
    document.feed(page)
    remote_id = (document.book_id or "").strip()
    if not remote_id or remote_id != path_id:
        raise SiteChanged("Comic detail identity does not match its path")
    title = _plain_text("".join(document.title_parts))
    if not title:
        title = _plain_text("".join(document.document_title_parts))
    if not title:
        raise SiteChanged("Comic detail has no title")
    hashes = [
        arguments for arguments in _javascript_calls(page, "data_book") if arguments
    ]
    if not hashes or len(hashes[0]) != 1:
        raise SiteChanged("Comic detail has no supported volume-data hash")
    data_hash = hashes[0][0].strip()
    if not data_hash or len(data_hash) > 512:
        raise SiteChanged("Comic detail volume-data hash is invalid")
    author_names = [_plain_text(value) for value in document.author_links]
    author_names = list(dict.fromkeys(value for value in author_names if value))
    author = ", ".join(author_names) or None
    author_text = _plain_text(" ".join(document.author_parts))
    language_match = LANGUAGE.search(author_text)
    language = language_match.group(1) if language_match else None
    return DetailPage(
        summary=ComicSummary(
            remote_id=remote_id,
            title=title,
            author=author,
            language=language,
            detail_path=normalized_path,
            cover_url=_normalize_url(document.cover_url, origin=origin),
        ),
        description=_extract_description(page),
        data_hash=data_hash,
    )


def normalize_detail_path(value: str, *, origin: str) -> tuple[str, str]:
    parsed = urlsplit(html.unescape(value.strip()))
    origin_host = urlsplit(origin).hostname
    if parsed.scheme or parsed.netloc:
        if parsed.scheme != "https" or parsed.hostname != origin_host:
            raise SiteChanged("Comic detail URL has an untrusted origin")
    match = DETAIL_PATH.fullmatch(parsed.path)
    if match is None or parsed.query or parsed.fragment:
        raise SiteChanged("Comic detail URL has an invalid path")
    return f"/c/{match.group(1)}.htm", match.group(1)


def _normalize_url(value: str | None, *, origin: str) -> str | None:
    if not value or not value.strip():
        return None
    resolved = urlsplit(urljoin(origin, html.unescape(value.strip())))
    if resolved.scheme != "https" or not resolved.hostname or resolved.username:
        raise SiteChanged("External asset URL is not trusted HTTPS")
    return resolved.geturl()


def _extract_description(page: str) -> str | None:
    match = DESCRIPTION_ASSIGNMENT.search(page)
    if match is None:
        return None
    position = match.end()
    while position < len(page) and page[position].isspace():
        position += 1
    if position >= len(page) or page[position] not in {'"', "'"}:
        raise SiteChanged("Comic description is not a string literal")
    value, _ = _read_javascript_string(page, position)
    return _plain_text(value) or None


def _plain_text(value: str) -> str:
    parser = _TextParser()
    parser.feed(html.unescape(value))
    return " ".join("".join(parser.parts).split())


def _javascript_calls(source: str, name: str) -> Iterator[list[str]]:
    marker = f"{name}("
    position = 0
    while True:
        start = source.find(marker, position)
        if start < 0:
            return
        declaration_prefix = source[max(0, start - 64) : start]
        if re.search(r"\bfunction\s*$", declaration_prefix):
            position = start + len(marker)
            continue
        arguments, position = _read_javascript_arguments(source, start + len(marker))
        yield arguments


def _read_javascript_arguments(source: str, position: int) -> tuple[list[str], int]:
    arguments: list[str] = []
    while position < len(source):
        while position < len(source) and source[position].isspace():
            position += 1
        if position < len(source) and source[position] == ")":
            return arguments, position + 1
        if position >= len(source):
            break
        if source[position] in {'"', "'"}:
            value, position = _read_javascript_string(source, position)
            while True:
                while position < len(source) and source[position].isspace():
                    position += 1
                if position >= len(source) or source[position] != "+":
                    break
                position += 1
                while position < len(source) and source[position].isspace():
                    position += 1
                if position >= len(source) or source[position] not in {'"', "'"}:
                    raise SiteChanged(
                        "JavaScript string concatenation has an unsupported operand"
                    )
                part, position = _read_javascript_string(source, position)
                value += part
        else:
            start = position
            while position < len(source) and source[position] not in ",)":
                position += 1
            value = source[start:position].strip()
        arguments.append(value)
        while position < len(source) and source[position].isspace():
            position += 1
        if position < len(source) and source[position] == ",":
            position += 1
            continue
        if position < len(source) and source[position] == ")":
            return arguments, position + 1
        break
    raise SiteChanged("JavaScript call is malformed")


def _read_javascript_string(source: str, position: int) -> tuple[str, int]:
    quote = source[position]
    position += 1
    result: list[str] = []
    while position < len(source):
        character = source[position]
        position += 1
        if character == quote:
            return "".join(result), position
        if character != "\\":
            result.append(character)
            continue
        if position >= len(source):
            break
        escaped = source[position]
        position += 1
        if escaped in {"u", "x"}:
            length = 4 if escaped == "u" else 2
            digits = source[position : position + length]
            if len(digits) != length or not all(
                value in "0123456789abcdefABCDEF" for value in digits
            ):
                raise SiteChanged("JavaScript string has an invalid escape")
            result.append(chr(int(digits, 16)))
            position += length
        else:
            result.append(JAVASCRIPT_ESCAPES.get(escaped, escaped))
    raise SiteChanged("JavaScript string is unterminated")


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
