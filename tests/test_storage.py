from __future__ import annotations

from pathlib import Path

import pytest

from kmoe_subscriptions.kmoe.schemas import ContentType, DownloadFormat
from kmoe_subscriptions.storage import (
    FileConflict,
    FileIntegrityError,
    download_paths,
    library_directory,
    prepare_download,
    promote_download,
    safe_component,
)


def test_safe_paths_cannot_escape_download_root(tmp_path: Path) -> None:
    root = tmp_path / "downloads"
    library = library_directory("../../危险:漫画", "../50076")
    paths = download_paths(
        root,
        library_dir=library,
        content_type=ContentType.VOLUME,
        item_name="../Volume/1\x00",
        item_id="../../v101",
        download_format=DownloadFormat.EPUB,
    )
    assert paths.final.is_relative_to(root.resolve())
    assert paths.final.parent.name == "volumes"
    assert paths.final.suffix == ".epub"
    assert ".." not in paths.final.relative_to(root.resolve()).parts
    assert safe_component("CON") == "_CON"


def test_promotes_only_complete_nonempty_files_atomically(tmp_path: Path) -> None:
    paths = download_paths(
        tmp_path,
        library_dir="Test comic [50076]",
        content_type=ContentType.EXTRA,
        item_name="Extra 1",
        item_id="e201",
        download_format=DownloadFormat.MOBI,
    )
    prepare_download(paths)
    paths.temporary.write_bytes(b"complete")
    assert promote_download(paths, expected_bytes=8) == 8
    assert paths.final.read_bytes() == b"complete"
    assert not paths.temporary.exists()
    with pytest.raises(FileConflict):
        prepare_download(paths)

    incomplete = download_paths(
        tmp_path,
        library_dir="Test comic [50076]",
        content_type=ContentType.EXTRA,
        item_name="Extra 2",
        item_id="e202",
        download_format=DownloadFormat.MOBI,
    )
    prepare_download(incomplete)
    incomplete.temporary.write_bytes(b"short")
    with pytest.raises(FileIntegrityError):
        promote_download(incomplete, expected_bytes=10)
    assert incomplete.temporary.exists()
    assert not incomplete.final.exists()
