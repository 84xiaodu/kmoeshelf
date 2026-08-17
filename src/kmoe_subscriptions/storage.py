from __future__ import annotations

import os
import re
import secrets
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


class InvalidStoragePath(StorageError):
    code = "invalid_storage_path"


class StoragePathSymlink(StorageError):
    code = "storage_path_symlink"


class StorageNotWritable(StorageError):
    code = "storage_not_writable"


@dataclass(frozen=True, slots=True)
class DownloadPaths:
    temporary: Path
    final: Path


class StorageBoundary:
    def __init__(self, root: Path) -> None:
        root = root.expanduser()
        if root.is_symlink():
            raise StoragePathSymlink("Storage root cannot be a symbolic link")
        self.root = root.resolve()

    def normalize_subpath(self, value: str) -> str:
        if "\x00" in value or "\\" in value:
            raise InvalidStoragePath("Storage path has unsupported characters")
        stripped = value.strip()
        if stripped.startswith("/"):
            raise InvalidStoragePath("Storage path must be relative")
        stripped = stripped.strip("/")
        if not stripped or stripped == ".":
            return ""
        candidate = Path(stripped)
        if candidate.is_absolute() or any(
            part in {"", ".", ".."} for part in candidate.parts
        ):
            raise InvalidStoragePath("Storage path must stay below the mounted root")
        if re.match(r"^[A-Za-z]:", stripped):
            raise InvalidStoragePath("Host absolute paths are not valid in the Web UI")
        return "/".join(candidate.parts)

    def directory(self, subpath: str, *, create: bool = False) -> Path:
        normalized = self.normalize_subpath(subpath)
        current = self.root
        if not current.exists():
            if create:
                current.mkdir(parents=True)
            else:
                raise InvalidStoragePath("Mounted storage root does not exist")
        if not current.is_dir():
            raise InvalidStoragePath("Mounted storage root is not a directory")
        for component in Path(normalized).parts if normalized else ():
            current = current / component
            if current.exists() or current.is_symlink():
                metadata = os.lstat(current)
                if stat.S_ISLNK(metadata.st_mode):
                    raise StoragePathSymlink("Storage path contains a symbolic link")
                if not stat.S_ISDIR(metadata.st_mode):
                    raise InvalidStoragePath("Storage path component is not a directory")
            elif create:
                current.mkdir()
            else:
                raise InvalidStoragePath("Storage directory does not exist")
        resolved = current.resolve()
        if not resolved.is_relative_to(self.root):
            raise InvalidStoragePath("Storage path escaped the mounted root")
        return resolved

    def managed_path(self, subpath: str, relative_path: str) -> Path:
        base = self.directory(subpath)
        normalized = self.normalize_subpath(relative_path)
        if not normalized:
            raise InvalidStoragePath("Managed file path cannot be empty")
        path = base.joinpath(*Path(normalized).parts)
        parent = path.parent
        relative_parent = parent.relative_to(base)
        self.directory(
            "/".join(
                part
                for part in (
                    self.normalize_subpath(subpath),
                    *relative_parent.parts,
                )
                if part
            ),
            create=True,
        )
        if path.is_symlink():
            raise StoragePathSymlink("Managed file path cannot be a symbolic link")
        resolved = path.resolve()
        if not resolved.is_relative_to(base):
            raise InvalidStoragePath("Managed file escaped the active storage directory")
        return resolved

    def list_directories(self, subpath: str = "") -> tuple[str, ...]:
        directory = self.directory(subpath)
        children: list[str] = []
        for child in directory.iterdir():
            metadata = child.lstat()
            if stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
                children.append(child.name)
        return tuple(sorted(children, key=str.casefold))

    def create_directory(self, subpath: str) -> Path:
        return self.directory(subpath, create=True)

    def assert_writable(self, subpath: str) -> Path:
        directory = self.directory(subpath, create=True)
        probe = directory / f".kmoe-write-test-{secrets.token_hex(8)}"
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(probe, flags, 0o600)
            os.close(descriptor)
        except OSError as exc:
            raise StorageNotWritable("Storage directory is not writable") from exc
        finally:
            probe.unlink(missing_ok=True)
        return directory


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
