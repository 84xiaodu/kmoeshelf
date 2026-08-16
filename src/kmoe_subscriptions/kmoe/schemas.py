from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ContentType(StrEnum):
    VOLUME = "volume"
    EXTRA = "extra"
    SERIAL = "serial"


class DownloadFormat(StrEnum):
    EPUB = "epub"
    MOBI = "mobi"


class AdapterModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ComicSummary(AdapterModel):
    remote_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    author: str | None = None
    language: str | None = None
    detail_path: str = Field(pattern=r"^/")
    cover_url: str | None = None


class SearchPage(AdapterModel):
    query: str = Field(min_length=1)
    current_page: int = Field(ge=1)
    total_pages: int = Field(ge=1)
    results: tuple[ComicSummary, ...] = ()


class RemoteItem(AdapterModel):
    remote_id: str = Field(min_length=1)
    content_type: ContentType
    name: str = Field(min_length=1)
    sort_order: int | None = None
    page_count: int | None = Field(default=None, ge=0)
    mobi_size_mb: Decimal | None = Field(default=None, ge=0)
    epub_size_mb: Decimal | None = Field(default=None, ge=0)


class ComicDetails(ComicSummary):
    description: str | None = None
    items: tuple[RemoteItem, ...] = ()
