from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Admin(Base):
    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(primary_key=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow
    )


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    admin_id: Mapped[int] = mapped_column(
        ForeignKey("admins.id", ondelete="CASCADE"), index=True
    )
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class KmoeCredential(Base):
    __tablename__ = "kmoe_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320))
    encrypted_cookies: Mapped[str] = mapped_column(Text)
    active_mirror: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="active")
    last_validated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class InitializationStrategy(StrEnum):
    BACKFILL = "backfill"
    FUTURE_ONLY = "future_only"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CheckStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Comic(Base):
    __tablename__ = "comics"

    id: Mapped[int] = mapped_column(primary_key=True)
    remote_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    author: Mapped[str | None] = mapped_column(String(255))
    language: Mapped[str | None] = mapped_column(String(32))
    detail_path: Mapped[str] = mapped_column(String(255))
    cover_url: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    comic_id: Mapped[int] = mapped_column(
        ForeignKey("comics.id", ondelete="CASCADE"), unique=True, index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    content_types: Mapped[list[str]] = mapped_column(JSON)
    download_format: Mapped[str] = mapped_column(String(8))
    initialization_strategy: Mapped[str] = mapped_column(String(16))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    last_error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class AppSetting(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    check_interval_hours: Mapped[int] = mapped_column(Integer, default=6)
    check_concurrency: Mapped[int] = mapped_column(Integer, default=1)
    download_concurrency: Mapped[int] = mapped_column(Integer, default=2)
    max_download_retries: Mapped[int] = mapped_column(Integer, default=3)
    preferred_mirror: Mapped[str] = mapped_column(String(255), default="mox.moe")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class CheckBatch(Base):
    __tablename__ = "check_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    trigger: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(
        String(16), default=CheckStatus.PENDING.value, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class SubscriptionCheck(Base):
    __tablename__ = "subscription_checks"
    __table_args__ = (
        UniqueConstraint("batch_id", "subscription_id", name="uq_batch_subscription"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("check_batches.id", ondelete="CASCADE"), index=True
    )
    subscription_id: Mapped[int] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(16), default=CheckStatus.PENDING.value, index=True
    )
    discovered_count: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class RemoteItemRecord(Base):
    __tablename__ = "remote_items"
    __table_args__ = (
        UniqueConstraint(
            "comic_id", "content_type", "remote_id", name="uq_remote_item_identity"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    comic_id: Mapped[int] = mapped_column(
        ForeignKey("comics.id", ondelete="CASCADE"), index=True
    )
    remote_id: Mapped[str] = mapped_column(String(64))
    content_type: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(255))
    sort_order: Mapped[int | None] = mapped_column(Integer)
    page_count: Mapped[int | None] = mapped_column(Integer)
    mobi_size_mb: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    epub_size_mb: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class DownloadTask(Base):
    __tablename__ = "download_tasks"
    __table_args__ = (
        UniqueConstraint("remote_item_id", "download_format", name="uq_download_task_item_format"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    remote_item_id: Mapped[int] = mapped_column(
        ForeignKey("remote_items.id", ondelete="CASCADE"), index=True
    )
    download_format: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16), default=TaskStatus.PENDING.value, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    progress_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    total_bytes: Mapped[int | None] = mapped_column(BigInteger)
    temporary_path: Mapped[str | None] = mapped_column(Text)
    final_path: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class ActivityEvent(Base):
    __tablename__ = "activity_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    comic_id: Mapped[int | None] = mapped_column(
        ForeignKey("comics.id", ondelete="SET NULL"), index=True
    )
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
