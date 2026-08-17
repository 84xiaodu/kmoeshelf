from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..kmoe.schemas import ContentType, DownloadFormat
from ..models import (
    DownloadTask,
    InitializationStrategy,
    RemoteItemRecord,
    Subscription,
    TaskStatus,
)


@dataclass(frozen=True, slots=True)
class PolicyImpact:
    created: int = 0
    converted: int = 0
    reused: int = 0
    cancelled: int = 0
    retained_running: int = 0
    retained_completed: int = 0
    obsolete_temporary_paths: tuple[str, ...] = ()

    @property
    def wakes_downloads(self) -> bool:
        return self.created > 0 or self.converted > 0 or self.reused > 0


def _reset_task(task: DownloadTask) -> None:
    task.status = TaskStatus.PENDING.value
    task.attempt_count = 0
    task.next_attempt_at = None
    task.cancel_requested = False
    task.progress_bytes = 0
    task.total_bytes = None
    task.temporary_path = None
    task.final_path = None
    task.error_code = None
    task.error_message = None
    task.started_at = None
    task.completed_at = None


async def reconcile_policy(
    session: AsyncSession,
    subscription: Subscription,
    *,
    content_types: set[ContentType],
    download_format: DownloadFormat,
    strategy: InitializationStrategy,
    apply: bool,
) -> PolicyImpact:
    selected = {value.value for value in content_types}
    if not selected:
        raise ValueError("At least one content type must be selected")
    items = list(
        await session.scalars(
            select(RemoteItemRecord).where(
                RemoteItemRecord.comic_id == subscription.comic_id
            )
        )
    )
    item_by_id = {item.id: item for item in items}
    tasks = list(
        await session.scalars(
            select(DownloadTask).where(
                DownloadTask.remote_item_id.in_(item_by_id)
            )
        )
    )
    virtual: dict[tuple[int, str], tuple[DownloadTask | None, str]] = {
        (task.remote_item_id, task.download_format): (task, task.status)
        for task in tasks
    }
    created = converted = reused = cancelled = 0
    retained_running = retained_completed = 0
    obsolete_paths: list[str] = []
    target_format = download_format.value
    reactivated: set[int] = set()

    if subscription.download_format != target_format:
        for task in tasks:
            item = item_by_id[task.remote_item_id]
            if item.content_type not in selected or task.download_format == target_format:
                continue
            if task.status == TaskStatus.RUNNING.value:
                retained_running += 1
                continue
            if task.status == TaskStatus.COMPLETED.value:
                retained_completed += 1
                continue
            if task.status not in {
                TaskStatus.PENDING.value,
                TaskStatus.FAILED.value,
            }:
                continue
            old_key = (task.remote_item_id, task.download_format)
            target_key = (task.remote_item_id, target_format)
            target = virtual.get(target_key)
            if target is not None:
                reused += 1
                cancelled += 1
                virtual[old_key] = (task, TaskStatus.CANCELLED.value)
                target_task, target_status = target
                if target_status in {
                    TaskStatus.FAILED.value,
                    TaskStatus.CANCELLED.value,
                }:
                    virtual[target_key] = (target_task, TaskStatus.PENDING.value)
                    if target_task is not None:
                        reactivated.add(target_task.id)
                if apply:
                    task.status = TaskStatus.CANCELLED.value
                    task.cancel_requested = True
                    if target_task is not None and target_task.id in reactivated:
                        if target_task.temporary_path:
                            obsolete_paths.append(target_task.temporary_path)
                        _reset_task(target_task)
                continue
            converted += 1
            virtual.pop(old_key, None)
            virtual[target_key] = (task, TaskStatus.PENDING.value)
            if apply:
                if task.temporary_path:
                    obsolete_paths.append(task.temporary_path)
                task.download_format = target_format
                _reset_task(task)

    if strategy is InitializationStrategy.BACKFILL:
        for item in items:
            if item.content_type not in selected:
                continue
            key = (item.id, target_format)
            target = virtual.get(key)
            if target is None:
                created += 1
                virtual[key] = (None, TaskStatus.PENDING.value)
                if apply:
                    session.add(
                        DownloadTask(
                            remote_item_id=item.id,
                            download_format=target_format,
                        )
                    )
                continue
            task, status = target
            if status in {
                TaskStatus.FAILED.value,
                TaskStatus.CANCELLED.value,
            } and task is not None and task.id not in reactivated:
                reused += 1
                reactivated.add(task.id)
                virtual[key] = (task, TaskStatus.PENDING.value)
                if apply:
                    if task.temporary_path:
                        obsolete_paths.append(task.temporary_path)
                    _reset_task(task)

    if apply:
        subscription.content_types = sorted(selected)
        subscription.download_format = target_format
        subscription.initialization_strategy = strategy.value
        await session.flush()

    return PolicyImpact(
        created=created,
        converted=converted,
        reused=reused,
        cancelled=cancelled,
        retained_running=retained_running,
        retained_completed=retained_completed,
        obsolete_temporary_paths=tuple(dict.fromkeys(obsolete_paths)),
    )
