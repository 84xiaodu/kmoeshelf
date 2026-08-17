from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .auth import require_csrf, require_same_origin, require_session
from ..models import StorageMigration, StorageMigrationPhase
from ..services.storage_migrations import (
    StorageMigrationConflict,
    StorageMigrationService,
    StoragePreview,
)
from ..storage import StorageError


router = APIRouter(prefix="/api/storage", tags=["storage"])


class StoragePathInput(BaseModel):
    path: str = Field(default="", max_length=1024)


class DirectoryListing(BaseModel):
    path: str
    directories: tuple[str, ...]


class StorageMigrationPreviewView(BaseModel):
    source_subpath: str
    target_subpath: str
    total_files: int
    total_bytes: int


class StorageMigrationView(BaseModel):
    id: int
    source_subpath: str
    target_subpath: str
    phase: StorageMigrationPhase
    failed_phase: StorageMigrationPhase | None
    total_files: int
    processed_files: int
    total_bytes: int
    processed_bytes: int
    current_relative_path: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class StorageStatusView(BaseModel):
    mounted_root: str
    active_subpath: str
    effective_path: str
    writable: bool
    migration: StorageMigrationView | None


def migration_view(migration: StorageMigration | None) -> StorageMigrationView | None:
    if migration is None:
        return None
    return StorageMigrationView(
        id=migration.id,
        source_subpath=migration.source_subpath,
        target_subpath=migration.target_subpath,
        phase=StorageMigrationPhase(migration.phase),
        failed_phase=(
            StorageMigrationPhase(migration.failed_phase)
            if migration.failed_phase
            else None
        ),
        total_files=migration.total_files,
        processed_files=migration.processed_files,
        total_bytes=migration.total_bytes,
        processed_bytes=migration.processed_bytes,
        current_relative_path=migration.current_relative_path,
        error_code=migration.error_code,
        error_message=migration.error_message,
        created_at=migration.created_at,
        started_at=migration.started_at,
        completed_at=migration.completed_at,
    )


def storage_service(request: Request) -> StorageMigrationService:
    return request.app.state.storage_migration_service


def storage_error(exc: StorageError) -> HTTPException:
    status = 409 if isinstance(exc, StorageMigrationConflict) else 422
    return HTTPException(
        status_code=status,
        detail={"code": getattr(exc, "code", "storage_error"), "message": str(exc)},
    )


@router.get(
    "", response_model=StorageStatusView, dependencies=[Depends(require_session)]
)
async def status(request: Request) -> StorageStatusView:
    service = storage_service(request)
    try:
        subpath = await service.active_subpath()
        effective = service.boundary.assert_writable(subpath)
        migration = await service.current()
    except StorageError as exc:
        raise storage_error(exc) from exc
    return StorageStatusView(
        mounted_root=str(service.boundary.root),
        active_subpath=subpath,
        effective_path=str(effective),
        writable=True,
        migration=migration_view(migration),
    )


@router.get(
    "/directories",
    response_model=DirectoryListing,
    dependencies=[Depends(require_session)],
)
async def directories(
    request: Request,
    path: Annotated[str, Query(max_length=1024)] = "",
) -> DirectoryListing:
    service = storage_service(request)
    try:
        normalized = service.boundary.normalize_subpath(path)
        children = service.boundary.list_directories(normalized)
    except StorageError as exc:
        raise storage_error(exc) from exc
    return DirectoryListing(path=normalized, directories=children)


@router.post(
    "/directories",
    response_model=DirectoryListing,
    dependencies=[Depends(require_same_origin), Depends(require_csrf)],
)
async def create_directory(body: StoragePathInput, request: Request) -> DirectoryListing:
    service = storage_service(request)
    try:
        normalized = service.boundary.normalize_subpath(body.path)
        service.boundary.create_directory(normalized)
        parent = "/".join(normalized.split("/")[:-1])
        children = service.boundary.list_directories(parent)
    except StorageError as exc:
        raise storage_error(exc) from exc
    return DirectoryListing(path=parent, directories=children)


@router.post(
    "/migrations/preview",
    response_model=StorageMigrationPreviewView,
    dependencies=[Depends(require_same_origin), Depends(require_csrf)],
)
async def preview_migration(
    body: StoragePathInput, request: Request
) -> StorageMigrationPreviewView:
    try:
        preview: StoragePreview = await storage_service(request).preview(body.path)
    except StorageError as exc:
        raise storage_error(exc) from exc
    return StorageMigrationPreviewView(
        source_subpath=preview.source_subpath,
        target_subpath=preview.target_subpath,
        total_files=preview.total_files,
        total_bytes=preview.total_bytes,
    )


@router.post(
    "/migrations",
    response_model=StorageMigrationView,
    status_code=201,
    dependencies=[Depends(require_same_origin), Depends(require_csrf)],
)
async def start_migration(
    body: StoragePathInput, request: Request
) -> StorageMigrationView:
    try:
        migration = await storage_service(request).create(body.path)
    except StorageError as exc:
        raise storage_error(exc) from exc
    view = migration_view(migration)
    assert view is not None
    return view


@router.get(
    "/migrations/current",
    response_model=StorageMigrationView | None,
    dependencies=[Depends(require_session)],
)
async def current_migration(request: Request) -> StorageMigrationView | None:
    return migration_view(await storage_service(request).current())


@router.post(
    "/migrations/{migration_id}/retry",
    response_model=StorageMigrationView,
    dependencies=[Depends(require_same_origin), Depends(require_csrf)],
)
async def retry_migration(
    migration_id: int, request: Request
) -> StorageMigrationView:
    try:
        migration = await storage_service(request).retry(migration_id)
    except StorageError as exc:
        raise storage_error(exc) from exc
    view = migration_view(migration)
    assert view is not None
    return view
