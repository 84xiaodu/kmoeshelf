from __future__ import annotations

import asyncio
import errno
import re
import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from urllib.parse import urljoin

import httpx
from sqlalchemy import or_, select, update

from ..config import Settings
from ..db import Database
from ..kmoe.client import KmoeClient
from ..kmoe.credentials import decrypt_cookies
from ..kmoe.downloads import get_download_info, validate_download_url
from ..kmoe.errors import AuthenticationExpired, KmoeError, NetworkError
from ..kmoe.schemas import ContentType, DownloadFormat
from ..models import (
    ActivityEvent,
    AppSetting,
    Comic,
    DownloadTask,
    KmoeCredential,
    RemoteItemRecord,
    TaskStatus,
)
from ..security import utcnow
from ..storage import (
    FileConflict,
    StorageError,
    download_paths,
    library_directory,
    prepare_download,
    promote_download,
)


CONTENT_RANGE = re.compile(r"^bytes (\d+)-(\d+)/(\d+)$")
REDIRECTS = {301, 302, 303, 307, 308}


class DownloadCancelled(Exception):
    pass


class RetryableDownload(Exception):
    pass


class DownloadService:
    def __init__(
        self,
        database: Database,
        settings: Settings,
        kmoe_client_factory: Callable[[], KmoeClient],
        transfer_client_factory: Callable[[], httpx.AsyncClient],
    ) -> None:
        self.database = database
        self.settings = settings
        self.kmoe_client_factory = kmoe_client_factory
        self.transfer_client_factory = transfer_client_factory
        self._wake = asyncio.Event()
        self._workers: list[asyncio.Task[None]] = []
        self._stopping = False

    async def start(self) -> None:
        async with self.database.sessions.begin() as session:
            await session.execute(
                update(DownloadTask)
                .where(
                    DownloadTask.status == TaskStatus.RUNNING.value,
                    DownloadTask.cancel_requested.is_(True),
                )
                .values(status=TaskStatus.CANCELLED.value, completed_at=utcnow())
            )
            await session.execute(
                update(DownloadTask)
                .where(DownloadTask.status == TaskStatus.RUNNING.value)
                .values(status=TaskStatus.PENDING.value, started_at=None)
            )
            setting = await session.get(AppSetting, 1)
            concurrency = setting.download_concurrency if setting else 2
        self._workers = [
            asyncio.create_task(self._worker(), name=f"download-worker-{index}")
            for index in range(max(1, concurrency))
        ]
        self._wake.set()

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        if self._workers:
            await asyncio.gather(*self._workers)

    def wake(self) -> None:
        self._wake.set()

    async def _worker(self) -> None:
        while True:
            task_id = await self._claim()
            if task_id is not None:
                await self._process(task_id)
                continue
            if self._stopping:
                return
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=1)
            except TimeoutError:
                pass
            self._wake.clear()

    async def _claim(self) -> int | None:
        now = utcnow()
        async with self.database.sessions.begin() as session:
            candidate = (
                select(DownloadTask.id)
                .where(
                    DownloadTask.status == TaskStatus.PENDING.value,
                    DownloadTask.cancel_requested.is_(False),
                    or_(
                        DownloadTask.next_attempt_at.is_(None),
                        DownloadTask.next_attempt_at <= now,
                    ),
                )
                .order_by(DownloadTask.id)
                .limit(1)
                .scalar_subquery()
            )
            return await session.scalar(
                update(DownloadTask)
                .where(
                    DownloadTask.id == candidate,
                    DownloadTask.status == TaskStatus.PENDING.value,
                )
                .values(
                    status=TaskStatus.RUNNING.value,
                    attempt_count=DownloadTask.attempt_count + 1,
                    started_at=now,
                    next_attempt_at=None,
                    error_code=None,
                    error_message=None,
                )
                .returning(DownloadTask.id)
            )

    async def _process(self, task_id: int) -> None:
        try:
            async with self.database.sessions.begin() as session:
                task = await session.get(DownloadTask, task_id)
                if task is None:
                    return
                item = await session.get(RemoteItemRecord, task.remote_item_id)
                comic = await session.get(Comic, item.comic_id) if item else None
                credential = await session.get(KmoeCredential, 1)
                if item is None or comic is None:
                    raise StorageError("Download task source record is missing")
                if credential is None or credential.status != "active":
                    raise AuthenticationExpired("Kmoe login required")
                snapshot = decrypt_cookies(self.settings, credential.encrypted_cookies)
                if comic.library_dir is None:
                    comic.library_dir = library_directory(comic.title, comic.remote_id)
                paths = download_paths(
                    self.settings.download_dir,
                    library_dir=comic.library_dir,
                    content_type=ContentType(item.content_type),
                    item_name=item.name,
                    item_id=item.remote_id,
                    download_format=DownloadFormat(task.download_format),
                )
                task.temporary_path = str(paths.temporary)
                task.final_path = str(paths.final)
                book_id, item_id = comic.remote_id, item.remote_id
                download_format = DownloadFormat(task.download_format)
                expected = task.total_bytes
            if paths.final.exists():
                if expected and paths.final.stat().st_size == expected:
                    await self._complete(task_id, expected, str(paths.final))
                    return
                raise FileConflict("Final download file already exists")
            prepare_download(paths)
            client = self.kmoe_client_factory()
            client.active_mirror = snapshot.mirror
            client.set_cookies(snapshot.cookies, domain=snapshot.mirror)
            async with client:
                info = await get_download_info(
                    client,
                    book_id=book_id,
                    item_id=item_id,
                    download_format=download_format,
                )
            total = await self._transfer(task_id, info.url, paths.temporary)
            size = promote_download(paths, expected_bytes=total)
            await self._complete(task_id, size, str(paths.final))
        except DownloadCancelled:
            await self._cancel(task_id)
        except (RetryableDownload, NetworkError, httpx.RequestError) as exc:
            await self._fail(task_id, "network_error", "Temporary download failure", exc, True)
        except KmoeError as exc:
            await self._fail(task_id, exc.code, str(exc), exc, False)
        except StorageError as exc:
            await self._fail(task_id, exc.code, str(exc), exc, False)
        except OSError as exc:
            code = "disk_full" if exc.errno == errno.ENOSPC else "storage_error"
            await self._fail(task_id, code, "Download storage write failed", exc, False)
        except Exception as exc:
            await self._fail(
                task_id,
                "internal_error",
                f"Download failed with {type(exc).__name__}",
                exc,
                False,
            )

    async def _transfer(self, task_id: int, url: str, temporary: Path) -> int | None:
        existing = temporary.stat().st_size if temporary.exists() else 0
        current_url = url
        async with self.transfer_client_factory() as client:
            for _ in range(4):
                if await self._cancel_requested(task_id):
                    raise DownloadCancelled
                validate_download_url(current_url)
                headers = {"Range": f"bytes={existing}-"} if existing else {}
                async with client.stream("GET", current_url, headers=headers) as response:
                    if response.status_code in REDIRECTS:
                        location = response.headers.get("location")
                        if not location:
                            raise RetryableDownload("Redirect has no location")
                        current_url = urljoin(current_url, location)
                        continue
                    if response.status_code >= 500:
                        raise RetryableDownload("Download server failed")
                    if response.status_code in {401, 403, 404, 408, 410, 429}:
                        raise RetryableDownload("Download URL expired or throttled")
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").lower()
                    if "text/html" in content_type or "application/json" in content_type:
                        raise RetryableDownload("Download returned non-file content")
                    mode = "ab"
                    total: int | None = None
                    if existing and response.status_code == 206:
                        match = CONTENT_RANGE.fullmatch(
                            response.headers.get("content-range", "")
                        )
                        if match is None or int(match.group(1)) != existing:
                            raise RetryableDownload("Resume range does not match")
                        total = int(match.group(3))
                    elif response.status_code == 200:
                        existing = 0
                        mode = "wb"
                        length = response.headers.get("content-length")
                        total = int(length) if length and length.isdigit() else None
                    else:
                        raise RetryableDownload("Download range response is invalid")
                    written = existing
                    persisted = existing
                    last_update = time.monotonic()
                    temporary.parent.mkdir(parents=True, exist_ok=True)
                    with temporary.open(mode) as output:
                        async for chunk in response.aiter_bytes(256 * 1024):
                            if await self._cancel_requested(task_id):
                                raise DownloadCancelled
                            output.write(chunk)
                            written += len(chunk)
                            if (
                                written - persisted >= 1024 * 1024
                                or time.monotonic() - last_update >= 1
                            ):
                                await self._progress(task_id, written, total)
                                persisted = written
                                last_update = time.monotonic()
                    if written != persisted:
                        await self._progress(task_id, written, total)
                    return total
            raise RetryableDownload("Too many download redirects")

    async def _cancel_requested(self, task_id: int) -> bool:
        async with self.database.sessions() as session:
            return bool(
                await session.scalar(
                    select(DownloadTask.cancel_requested).where(
                        DownloadTask.id == task_id
                    )
                )
            )

    async def _progress(self, task_id: int, progress: int, total: int | None) -> None:
        async with self.database.sessions.begin() as session:
            await session.execute(
                update(DownloadTask)
                .where(DownloadTask.id == task_id)
                .values(progress_bytes=progress, total_bytes=total)
            )

    async def _complete(self, task_id: int, size: int, final_path: str) -> None:
        async with self.database.sessions.begin() as session:
            task = await session.get(DownloadTask, task_id)
            if task is None:
                return
            task.status = TaskStatus.COMPLETED.value
            task.progress_bytes = size
            task.total_bytes = size
            task.final_path = final_path
            task.completed_at = utcnow()
            task.cancel_requested = False
            session.add(
                ActivityEvent(
                    event_type="download_completed",
                    comic_id=None,
                    message=f"Download task {task.id} completed",
                )
            )

    async def _cancel(self, task_id: int) -> None:
        async with self.database.sessions.begin() as session:
            await session.execute(
                update(DownloadTask)
                .where(DownloadTask.id == task_id)
                .values(status=TaskStatus.CANCELLED.value, completed_at=utcnow())
            )

    async def _fail(
        self,
        task_id: int,
        code: str,
        message: str,
        error: Exception,
        retryable: bool,
    ) -> None:
        async with self.database.sessions.begin() as session:
            task = await session.get(DownloadTask, task_id)
            setting = await session.get(AppSetting, 1)
            if task is None:
                return
            retries = setting.max_download_retries if setting else 3
            if retryable and task.attempt_count < retries:
                task.status = TaskStatus.PENDING.value
                task.next_attempt_at = utcnow() + timedelta(
                    seconds=min(60, 2**task.attempt_count)
                )
            else:
                task.status = TaskStatus.FAILED.value
                task.completed_at = utcnow()
            task.error_code = code
            task.error_message = message
            if isinstance(error, AuthenticationExpired):
                credential = await session.get(KmoeCredential, 1)
                if credential is not None:
                    credential.status = "expired"
