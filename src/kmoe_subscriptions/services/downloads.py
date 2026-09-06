from __future__ import annotations

import asyncio
import errno
import logging
import random
import re
import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
from sqlalchemy import exists, or_, select, update

from ..config import Settings
from ..db import Database
from ..kmoe.client import KmoeClient
from ..kmoe.credentials import decrypt_cookies
from ..kmoe.downloads import (
    TRANSFER_HEADERS,
    get_download_info,
    non_file_response,
    raise_for_transfer_status,
    validate_download_url,
)
from ..kmoe.errors import (
    AuthenticationExpired,
    DownloadConnectTimeout,
    DownloadRangeInvalid,
    DownloadTransferError,
    DownloadUrlExpired,
    KmoeError,
    NetworkError,
    RateLimited,
)
from ..kmoe.schemas import ContentType, DownloadFormat
from ..models import (
    ActivityEvent,
    AppSetting,
    Comic,
    DownloadTask,
    KmoeCredential,
    RemoteItemRecord,
    StorageMigration,
    StorageMigrationPhase,
    TaskStatus,
)
from ..security import utcnow
from ..storage import (
    FileConflict,
    StorageError,
    StorageBoundary,
    download_paths,
    library_directory,
    prepare_download,
    promote_download,
)


CONTENT_RANGE = re.compile(r"^bytes (\d+)-(\d+)/(\d+)$")
REDIRECTS = {301, 302, 303, 307, 308}
CANCEL_CHECK_BYTES = 8 * 1024 * 1024
CANCEL_CHECK_SECONDS = 0.5
logger = logging.getLogger(__name__)


class DownloadCancelled(Exception):
    pass


def retry_delay(attempt_count: int, *, jitter: float | None = None) -> float:
    base = min(60.0, float(2**attempt_count))
    value = random.random() if jitter is None else jitter
    if not 0 <= value <= 1:
        raise ValueError("Retry jitter must be between zero and one")
    return base + value * min(1.0, base / 4)


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
        self._workers: dict[int, asyncio.Task[None]] = {}
        self._desired_concurrency = 0
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
        self.set_concurrency(concurrency)

    async def stop(self) -> None:
        self._stopping = True
        self._desired_concurrency = 0
        self._wake.set()
        if self._workers:
            await asyncio.gather(*self._workers.values())

    @property
    def concurrency(self) -> int:
        return self._desired_concurrency

    def set_concurrency(self, concurrency: int) -> None:
        if not 1 <= concurrency <= 8:
            raise ValueError("download concurrency must be between 1 and 8")
        self._desired_concurrency = concurrency
        for index in range(concurrency):
            worker = self._workers.get(index)
            if worker is None or worker.done():
                self._workers[index] = asyncio.create_task(
                    self._worker(index), name=f"download-worker-{index}"
                )
        self._wake.set()

    def wake(self) -> None:
        self._wake.set()

    async def _worker(self, index: int) -> None:
        while index < self._desired_concurrency:
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
            migration_active = exists(
                select(StorageMigration.id).where(
                    StorageMigration.phase.in_(
                        (
                            StorageMigrationPhase.PENDING.value,
                            StorageMigrationPhase.WAITING_FOR_DOWNLOADS.value,
                            StorageMigrationPhase.COPYING.value,
                            StorageMigrationPhase.COMMITTING.value,
                            StorageMigrationPhase.CLEANING.value,
                        )
                    )
                )
            )
            candidate = (
                select(DownloadTask.id)
                .where(
                    ~migration_active,
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
                setting = await session.get(AppSetting, 1)
                if item is None or comic is None:
                    raise StorageError("Download task source record is missing")
                if credential is None or credential.status != "active":
                    raise AuthenticationExpired("Kmoe login required")
                snapshot = decrypt_cookies(self.settings, credential.encrypted_cookies)
                if comic.library_dir is None:
                    comic.library_dir = library_directory(comic.title, comic.remote_id)
                paths = download_paths(
                    StorageBoundary(self.settings.download_dir).directory(
                        setting.download_subpath if setting else "", create=True
                    ),
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
        except DownloadTransferError as exc:
            await self._fail(task_id, exc.code, str(exc), exc, exc.retryable)
        except RateLimited as exc:
            await self._fail(task_id, exc.code, str(exc), exc, True)
        except NetworkError as exc:
            await self._fail(task_id, exc.code, "Kmoe network request failed", exc, True)
        except httpx.TimeoutException as exc:
            safe = DownloadConnectTimeout("Download connection timed out")
            await self._fail(task_id, safe.code, str(safe), exc, True)
        except httpx.RequestError as exc:
            await self._fail(
                task_id,
                "network_error",
                f"Download connection failed with {type(exc).__name__}",
                exc,
                True,
            )
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
                host = urlsplit(current_url).hostname or "unknown-host"
                headers = dict(TRANSFER_HEADERS)
                if existing:
                    headers["Range"] = f"bytes={existing}-"
                async with client.stream("GET", current_url, headers=headers) as response:
                    if response.status_code in REDIRECTS:
                        location = response.headers.get("location")
                        if not location:
                            raise DownloadUrlExpired(
                                f"Download redirect at {host} has no location"
                            )
                        current_url = urljoin(current_url, location)
                        continue
                    if response.status_code == 416 and existing:
                        temporary.unlink(missing_ok=True)
                    raise_for_transfer_status(response.status_code, host=host)
                    content_type = response.headers.get("content-type", "").lower()
                    if "text/html" in content_type or "application/json" in content_type:
                        raise non_file_response(host=host)
                    mode = "ab"
                    total: int | None = None
                    if existing and response.status_code == 206:
                        match = CONTENT_RANGE.fullmatch(
                            response.headers.get("content-range", "")
                        )
                        if match is None or int(match.group(1)) != existing:
                            temporary.unlink(missing_ok=True)
                            raise DownloadRangeInvalid(
                                f"Download resume range from {host} does not match"
                            )
                        total = int(match.group(3))
                    elif response.status_code == 200:
                        existing = 0
                        mode = "wb"
                        length = response.headers.get("content-length")
                        total = int(length) if length and length.isdigit() else None
                    else:
                        temporary.unlink(missing_ok=True)
                        raise DownloadRangeInvalid(
                            f"Download range response from {host} is invalid"
                        )
                    written = existing
                    last_update = time.monotonic()
                    last_cancel_check = last_update
                    cancel_checked_at = written
                    temporary.parent.mkdir(parents=True, exist_ok=True)
                    with temporary.open(mode) as output:
                        async for chunk in response.aiter_bytes(256 * 1024):
                            output.write(chunk)
                            written += len(chunk)
                            now = time.monotonic()
                            if (
                                written - cancel_checked_at >= CANCEL_CHECK_BYTES
                                or now - last_cancel_check >= CANCEL_CHECK_SECONDS
                            ):
                                if await self._cancel_requested(task_id):
                                    raise DownloadCancelled
                                cancel_checked_at = written
                                last_cancel_check = now
                            if now - last_update >= 1:
                                await self._progress(task_id, written, total)
                                last_update = now
                    await self._progress(task_id, written, total)
                    return total
            raise DownloadUrlExpired("Download URL exceeded the redirect limit")

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
                    seconds=retry_delay(task.attempt_count)
                )
            else:
                task.status = TaskStatus.FAILED.value
                task.completed_at = utcnow()
            task.error_code = code
            task.error_message = message
            if task.status == TaskStatus.FAILED.value:
                logger.warning(
                    "download task failed",
                    extra={
                        "task_id": task.id,
                        "error_code": code,
                        "error_type": type(error).__name__,
                    },
                )
            if isinstance(error, AuthenticationExpired):
                credential = await session.get(KmoeCredential, 1)
                if credential is not None:
                    credential.status = "expired"
