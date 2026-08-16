from __future__ import annotations

import os
import re
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .kmoe.schemas import ContentType, DownloadFormat


ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{value}" for value in range(1, 10)),
    *(f"LPT{value}" for value in range(1, 10)),
}
CONTENT_DIRECTORIES = {
    ContentType.VOLUME: "volumes",
    ContentType.EXTRA: "extras",
    ContentType.SERIAL: "serials",
}


class StorageError(Exception):
    code = "storage_error"


class FileConflict(StorageError):
    code = "file_conflict"


class FileIntegrityError(StorageError):
    code = "file_integrity_error"


@dataclass(frozen=True, slots=True)
class DownloadPaths:
    temporary: Path
    final: Path


def safe_component(value: str, *, fallback: str = "untitled", limit: int = 96) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    cleaned = " ".join(ILLEGAL.sub("_", normalized).split()).strip(" .")
    if cleaned in {"", ".", ".."}:
        cleaned = fallback
    if cleaned.upper() in WINDOWS_RESERVED:
        cleaned = f"_{cleaned}"
    return cleaned[:limit].rstrip(" .") or fallback


def library_directory(title: str, comic_id: str) -> str:
    return f"{safe_component(title)} [{safe_component(comic_id, fallback='comic-id')}]"


def download_paths(
    root: Path,
    *,
    library_dir: str,
    content_type: ContentType,
    item_name: str,
    item_id: str,
    download_format: DownloadFormat,
) -> DownloadPaths:
    root = root.resolve()
    directory = root / safe_component(library_dir) / CONTENT_DIRECTORIES[content_type]
    filename = (
        f"{safe_component(item_name)} "
        f"[{safe_component(item_id, fallback='item-id')}].{download_format.value}"
    )
    final = (directory / filename).resolve()
    temporary = final.with_name(f"{final.name}.part")
    for path in (directory.resolve(), final, temporary):
        if not path.is_relative_to(root):
            raise StorageError("Download path escaped the configured root")
    return DownloadPaths(temporary=temporary, final=final)


def prepare_download(paths: DownloadPaths) -> None:
    paths.final.parent.mkdir(parents=True, exist_ok=True)
    if paths.final.exists():
        raise FileConflict("Final download file already exists")


def promote_download(paths: DownloadPaths, *, expected_bytes: int | None) -> int:
    if paths.final.exists():
        raise FileConflict("Final download file already exists")
    try:
        metadata = os.stat(paths.temporary, follow_symlinks=False)
    except FileNotFoundError as exc:
        raise FileIntegrityError("Temporary download file is missing") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise FileIntegrityError("Temporary download path is not a regular file")
    size = metadata.st_size
    if size <= 0:
        raise FileIntegrityError("Downloaded file is empty")
    if expected_bytes is not None and size != expected_bytes:
        raise FileIntegrityError("Downloaded file length does not match response")
    try:
        os.link(paths.temporary, paths.final, follow_symlinks=False)
    except FileExistsError as exc:
        raise FileConflict("Final download file already exists") from exc
    paths.temporary.unlink()
    return size
