from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from .auth import get_db, require_csrf, require_same_origin, require_session
from ..kmoe.schemas import ContentType, DownloadFormat
from ..models import Comic, DownloadTask, RemoteItemRecord, TaskStatus
from ..security import utcnow


router = APIRouter(prefix="/api/downloads", tags=["downloads"])
# ponytail: completed history is bounded; add a cursor if full history matters.
RECENT_TASK_LIMIT = 100


class DownloadTaskView(BaseModel):
    id: int
    comic_id: int
    comic_remote_id: str
    comic_title: str
    item_remote_id: str
    item_name: str
    content_type: ContentType
    download_format: DownloadFormat
    status: TaskStatus
    attempt_count: int
    progress_bytes: int
    total_bytes: int | None
    final_path: str | None
    error_code: str | None
    error_message: str | None
    next_attempt_at: datetime | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class DownloadStatusCounts(BaseModel):
    pending: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0


class DownloadSnapshot(BaseModel):
    tasks: list[DownloadTaskView]
    counts: DownloadStatusCounts


def task_view(
    task: DownloadTask, item: RemoteItemRecord, comic: Comic
) -> DownloadTaskView:
    return DownloadTaskView(
        id=task.id,
        comic_id=comic.id,
        comic_remote_id=comic.remote_id,
        comic_title=comic.title,
        item_remote_id=item.remote_id,
        item_name=item.name,
        content_type=ContentType(item.content_type),
        download_format=DownloadFormat(task.download_format),
        status=TaskStatus(task.status),
        attempt_count=task.attempt_count,
        progress_bytes=task.progress_bytes,
        total_bytes=task.total_bytes,
        final_path=task.final_path,
        error_code=task.error_code,
        error_message=task.error_message,
        next_attempt_at=task.next_attempt_at,
        created_at=task.created_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
    )


async def get_task_row(
    db: AsyncSession, task_id: int
) -> tuple[DownloadTask, RemoteItemRecord, Comic]:
    row = (
        await db.execute(
            select(DownloadTask, RemoteItemRecord, Comic)
            .join(RemoteItemRecord, RemoteItemRecord.id == DownloadTask.remote_item_id)
            .join(Comic, Comic.id == RemoteItemRecord.comic_id)
            .where(DownloadTask.id == task_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Download task not found")
    return row[0], row[1], row[2]


async def load_download_snapshot(
    db: AsyncSession,
    *,
    status: TaskStatus | None = None,
    comic_id: int | None = None,
) -> DownloadSnapshot:
    statement = (
        select(DownloadTask, RemoteItemRecord, Comic)
        .join(RemoteItemRecord, RemoteItemRecord.id == DownloadTask.remote_item_id)
        .join(Comic, Comic.id == RemoteItemRecord.comic_id)
    )
    count_statement = select(DownloadTask.status, func.count(DownloadTask.id)).join(
        RemoteItemRecord, RemoteItemRecord.id == DownloadTask.remote_item_id
    )
    if comic_id is not None:
        statement = statement.where(Comic.id == comic_id)
        count_statement = count_statement.where(RemoteItemRecord.comic_id == comic_id)
    count_rows = (await db.execute(count_statement.group_by(DownloadTask.status))).all()
    counts = DownloadStatusCounts(
        **{task_status: count for task_status, count in count_rows}
    )

    if status is not None:
        statement = statement.where(DownloadTask.status == status.value).order_by(
            DownloadTask.id.desc()
        )
        if status == TaskStatus.COMPLETED:
            statement = statement.limit(RECENT_TASK_LIMIT)
        rows = (await db.execute(statement)).all()
    else:
        running = (
            await db.execute(
                statement.where(DownloadTask.status == TaskStatus.RUNNING.value).order_by(
                    DownloadTask.id.desc()
                )
            )
        ).all()
        recent = (
            await db.execute(
                statement.where(DownloadTask.status != TaskStatus.RUNNING.value)
                .order_by(DownloadTask.id.desc())
                .limit(RECENT_TASK_LIMIT)
            )
        ).all()
        rows = sorted((*running, *recent), key=lambda row: row[0].id, reverse=True)
    return DownloadSnapshot(
        tasks=[task_view(task, item, comic) for task, item, comic in rows],
        counts=counts,
    )


def serialize_event(snapshot: DownloadSnapshot) -> str:
    payload = snapshot.model_dump(mode="json")
    return f"event: downloads\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.get(
    "",
    response_model=DownloadSnapshot,
    dependencies=[Depends(require_session)],
)
async def list_downloads(
    db: Annotated[AsyncSession, Depends(get_db)],
    status: Annotated[TaskStatus | None, Query()] = None,
    comic_id: Annotated[int | None, Query(ge=1)] = None,
) -> DownloadSnapshot:
    return await load_download_snapshot(db, status=status, comic_id=comic_id)


@router.get("/events", dependencies=[Depends(require_session)])
async def download_events(
    request: Request,
    status: Annotated[TaskStatus | None, Query()] = None,
) -> StreamingResponse:
    async def stream():
        previous: str | None = None
        while not await request.is_disconnected():
            async with request.app.state.database.sessions() as session:
                event = serialize_event(
                    await load_download_snapshot(session, status=status)
                )
            if event != previous:
                yield event
                previous = event
            else:
                yield ": keepalive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/{task_id}",
    response_model=DownloadTaskView,
    dependencies=[Depends(require_session)],
)
async def download_status(
    task_id: int, db: Annotated[AsyncSession, Depends(get_db)]
) -> DownloadTaskView:
    return task_view(*await get_task_row(db, task_id))


@router.post(
    "/{task_id}/cancel",
    response_model=DownloadTaskView,
    dependencies=[Depends(require_same_origin), Depends(require_csrf)],
)
async def cancel_download(
    task_id: int,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DownloadTaskView:
    task, item, comic = await get_task_row(db, task_id)
    if task.status == TaskStatus.PENDING.value:
        task.status = TaskStatus.CANCELLED.value
        task.cancel_requested = True
        task.completed_at = utcnow()
    elif task.status == TaskStatus.RUNNING.value:
        task.cancel_requested = True
    elif task.status != TaskStatus.CANCELLED.value:
        raise HTTPException(status_code=409, detail="Download cannot be cancelled")
    await db.commit()
    request.app.state.download_service.wake()
    return task_view(task, item, comic)


@router.post(
    "/{task_id}/retry",
    response_model=DownloadTaskView,
    dependencies=[Depends(require_same_origin), Depends(require_csrf)],
)
async def retry_download(
    task_id: int,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DownloadTaskView:
    task, item, comic = await get_task_row(db, task_id)
    if task.status not in {TaskStatus.FAILED.value, TaskStatus.CANCELLED.value}:
        raise HTTPException(status_code=409, detail="Download cannot be retried")
    task.status = TaskStatus.PENDING.value
    task.cancel_requested = False
    task.next_attempt_at = None
    task.completed_at = None
    task.error_code = None
    task.error_message = None
    await db.commit()
    request.app.state.download_service.wake()
    return task_view(task, item, comic)
