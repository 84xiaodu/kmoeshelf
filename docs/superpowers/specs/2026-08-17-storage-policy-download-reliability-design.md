# Storage, Subscription Policy, and Download Reliability Design

Date: 2026-08-17
Status: design decisions approved; written specification pending user review

## Context

The service currently has three related gaps:

1. A live EPUB download for `琉璃龍龍` / `卷 01` failed after four attempts with zero bytes transferred. The persisted error is only `network_error: Temporary download failure`, so the operator cannot distinguish an expired signed URL, a rejected transfer, quota exhaustion, or a network timeout.
2. Docker fixes the download root at `/downloads`. The Web UI cannot select a persistent location under a host-mounted storage root, and there is no safe migration workflow for completed files.
3. Existing subscriptions can edit content types and format, but cannot edit the `future_only` / `backfill` strategy or preview and reconcile the resulting download tasks.

The two reference clients support configurable destinations. The more recent downloader also documents that its default download method has account-dependent resume limitations. This design retains the current direct-file architecture while making protocol handling, storage changes, and policy reconciliation explicit and recoverable.

References:

- <https://github.com/holdjun/kmoe>
- <https://github.com/chrisis58/kmoe-manga-downloader>
- `docs/handoffs/kmoe-adapter-research.md`

## Goals

- Fix the current pre-transfer download failure and expose a precise, safe failure reason when an upstream condition still prevents completion.
- Mount one host storage root at deployment time and let an administrator choose any safe subdirectory under it from the Web UI.
- Automatically migrate application-managed completed files when the active storage subdirectory changes.
- Make storage migration persistent, resumable, observable, and safe across process restarts.
- Let an administrator edit subscription content types, download format, and initialization strategy with a preview of the task impact.
- Reconcile task state deterministically without deleting completed downloads or duplicating tasks.

## Non-goals

- The Web application will not mount arbitrary host paths or control Docker.
- The container will not receive access to the Docker socket.
- A Web storage change cannot migrate from a host directory that is no longer mounted into the container.
- Unmanaged files under the old storage directory will not be moved or deleted.
- Completed files in an old ebook format will not be deleted automatically after a subscription format change.
- This work will not introduce a generic job framework or multi-account quota pool.
- This work will not add multipart or parallel-range downloads.

## 1. Storage architecture

### 1.1 Deployment boundary

Compose will use a host interpolation variable:

```yaml
volumes:
  - ${KMOE_STORAGE_HOST_ROOT:-./downloads}:/storage
```

`KMOE_STORAGE_HOST_ROOT` is configured once by the operator in `.env`. The application sees only the fixed container root `/storage`. It never receives, stores, or interprets a Windows host path such as `D:\漫画`.

The default remains `./downloads`, so an existing installation that does not set the new variable keeps the same host files. On upgrade, legacy database paths rooted at `/downloads` are translated to `/storage` because both paths refer to the same default host directory. Pending and failed task paths are cleared and recomputed when the task next runs.

Changing `KMOE_STORAGE_HOST_ROOT` later is a deployment operation: stop the service, move or expose the old host data under the new mount, update `.env`, and recreate the container. Web-managed automatic migration applies only to subdirectories within the currently mounted `/storage` tree.

### 1.2 Active location

`AppSetting` gains `download_subpath`, stored as a normalized POSIX-style relative path. An empty value means the `/storage` root itself. The effective root is:

```text
/storage/<download_subpath>
```

The immutable allowed root remains application configuration. The mutable subpath is database state. Download workers read the active subpath when claiming and preparing each task rather than caching it at service startup.

### 1.3 Path validation

All storage APIs use one storage-boundary component that:

- accepts only relative paths;
- rejects absolute paths, `..`, NUL characters, and empty path components created by malformed input;
- normalizes separators for storage but does not accept a host-native absolute path;
- resolves each existing component with `lstat` and rejects symbolic links;
- verifies that the resolved target stays under `/storage`;
- creates requested directories one component at a time;
- verifies writability using a uniquely named temporary file created with exclusive semantics and then removes it;
- never follows a symbolic link during directory listing, migration, or cleanup.

Existing filename sanitization remains responsible for comic, content-type, and item filename components.

## 2. Persistent storage migration

### 2.1 Data model

Add `StorageMigration` with:

- `id`
- `source_subpath`
- `target_subpath`
- `phase`: `pending`, `waiting_for_downloads`, `copying`, `committing`, `cleaning`, `completed`, or `failed`
- `total_files`, `processed_files`
- `total_bytes`, `processed_bytes`
- `current_relative_path`
- `failed_phase`, used to resume the interrupted phase after an operator retry
- `error_code`, `error_message`
- `created_at`, `started_at`, `completed_at`, `updated_at`

Add `StorageMigrationFile` with:

- migration and completed download-task identifiers;
- source and target relative paths;
- expected size;
- state: `pending`, `copied`, `committed`, `cleaned`, or `conflict`;
- safe error details.

At most one migration may be active. The database constraint and service-level transaction both enforce this.

### 2.2 Preflight and creation

The preview endpoint validates the target, tests writability, enumerates completed tasks whose managed files exist, checks target conflicts, and reports file and byte totals. Preview does not mutate state, and its totals are advisory because a running download may finish before migration starts.

Creation repeats target validation rather than trusting stale preview values. It persists the migration request and then wakes the migration service. The per-file plan is deliberately not frozen until download workers have stopped claiming and every already-running download has finished. At that point, the service enumerates completed tasks again and persists the final per-file plan in one transaction. This guarantees that a file completed while the migration was waiting is included.

If there are no managed completed files, the job still passes through the same commit step and changes the active subpath without copying.

### 2.3 Coordination with downloads

When an active storage migration exists:

- download workers stop claiming new tasks;
- already running downloads finish against the old active root;
- subscription checks continue and may create pending download tasks;
- migration waits until no task is `running` before copying;
- on application restart, migration recovery runs before new download claims are allowed.

The migration pause is database-authoritative. In-memory events are only wake-up optimizations.

### 2.4 Copy, commit, and cleanup

For every planned file:

1. Revalidate both source and target paths under `/storage` without following symlinks.
2. Copy to a uniquely named sibling file ending in `.migrating`.
3. Flush and close the destination.
4. Verify that its byte size equals the completed task's recorded size or the source file size when legacy data lacks a recorded size.
5. Atomically rename the staged file to its final target.
6. Mark the per-file row as copied and advance persistent progress.

If a target file already exists with the expected size, reuse it. If its size differs, mark a conflict and fail the migration without changing the active root or deleting source files.

After every file is copied, one database transaction:

- changes `AppSetting.download_subpath`;
- updates completed task `final_path` values;
- clears temporary and final paths on pending, failed, and cancelled tasks so they are recomputed;
- marks copied migration files as committed;
- advances the migration to cleanup.

Cleanup deletes only committed source files listed in `StorageMigrationFile`. It then removes empty directories created by the application, stopping at the old effective root. Other files and non-empty directories remain untouched.

### 2.5 Crash recovery

- Before the database commit, the old root remains authoritative and no source is deleted. Existing same-size target copies are reused on retry.
- After the database commit, the new root is authoritative. Cleanup may be resumed without recopying.
- A copy or conflict failure leaves the migration failed and the old root active.
- A cleanup failure leaves the migration failed in the cleanup phase but keeps the new root active; retry continues cleanup only.
- Administrators can retry a failed migration from its recorded `failed_phase`. They cannot start a second migration until the first migration has completed successfully; a reported conflict or permission error must be corrected and the same migration retried.

## 3. Subscription policy editing

### 3.1 Editable policy

The subscription editor exposes:

- content types: volume, extra, and serial;
- download format: EPUB or MOBI;
- initialization strategy: `future_only` or `backfill`.

The existing subscription response continues to expose the active policy. `SubscriptionEdit` gains `initialization_strategy`.

### 3.2 Preview

A policy-preview endpoint accepts the proposed policy and reports:

- historical tasks that would be created;
- pending or failed tasks that would be converted to a new format;
- duplicate target-format tasks that would be reused;
- running and completed old-format tasks that would be retained;
- tasks outside newly selected content types that would remain unchanged.

Preview is advisory. Apply recalculates the plan transactionally so a check finishing between preview and confirmation cannot create duplicates.

### 3.3 Reconciliation rules

All reconciliation occurs in the same database transaction as the subscription update.

- `future_only` to `backfill`: create current-format tasks for all matching historical items without an equivalent task or completed file.
- `backfill` to `future_only`: stop future historical backfill creation. Already queued tasks remain.
- Adding a content type under `backfill`: create missing current-format historical tasks for the added type.
- Adding a content type under `future_only`: only future discoveries create tasks.
- Removing a content type: stop future task creation for that type. Existing queued, running, failed, cancelled, and completed tasks remain.
- Changing format applies conversion only to pending or failed tasks whose content type remains selected.
- Converted failed tasks return to pending, reset retry scheduling and attempt count, clear old errors and paths, and wake the worker.
- Running old-format tasks finish unchanged.
- Completed old-format files remain unchanged.
- Under `backfill`, changing format also creates missing new-format tasks for matching historical items.

If an equivalent new-format task already exists, it is reused. The old pending or failed task is marked cancelled rather than changed into a uniqueness conflict. Existing completed new-format tasks satisfy backfill and are not recreated.

The update creates an activity event summarizing created, converted, reused, cancelled, and retained task counts.

## 4. Download protocol and diagnostics

### 4.1 Two-stage boundary

The adapter retains two separate clients:

1. The authenticated Kmoe client calls `/getdownurl.php` and receives a short-lived URL.
2. An unauthenticated transfer client downloads from the validated public HTTPS URL.

Cookies and signed URLs must never be logged or persisted. Redirect targets are validated at every hop. The transfer client sends no Kmoe Cookie or authorization value.

### 4.2 Transfer behavior

- Actual file requests include `X-Km-From: kb_http_down`, matching the known refer-via reference implementation.
- A new transfer starts without `Range`.
- A non-empty `.part` file may request `Range: bytes=<size>-`.
- A valid `206` must have a matching `Content-Range` start and total.
- If a server ignores Range and returns `200`, the worker truncates the `.part` file and safely restarts from byte zero.
- A retry at task level reacquires a fresh short-lived URL.
- Redirects are bounded and validated.
- HTML and JSON responses are rejected as non-file content.
- Final promotion remains no-clobber and verifies a positive file size and any known response length.

### 4.3 Error taxonomy

Replace the generic transfer failure with safe codes:

- `auth_expired`
- `quota_exhausted`
- `download_url_expired`
- `download_forbidden`
- `rate_limited`
- `connect_timeout`
- `download_server_error`
- `non_file_response`
- `download_range_invalid`
- existing storage and integrity errors

Retryability is determined by code. Authentication, quota, unsafe URL, file conflict, and deterministic storage failures do not consume repeated automatic attempts. Expired URLs, timeouts, rate limits, and server failures may retry with existing bounded backoff.

Stored diagnostics may contain an HTTP status, public host, stage, and exception class. They must not contain query strings, signed paths, cookies, credentials, or response bodies. The service emits structured warning logs and activity events for terminal failures.

### 4.4 Live acceptance

After deployment, reset the current failed `琉璃龍龍` / `卷 01` EPUB task to pending once and monitor it. Acceptance is either:

- the file completes with a non-zero verified size at the active storage root; or
- the UI and database report a precise upstream condition such as quota exhaustion or transfer rejection, with no secret data exposed.

An upstream account or quota denial is not treated as an application success, but it must no longer appear as an unexplained generic network failure.

## 5. API and Web UI

### 5.1 Storage APIs

Add authenticated, same-origin, CSRF-protected mutation routes and session-protected read routes:

- `GET /api/storage`: mount health, active subpath, effective container path, and active migration summary.
- `GET /api/storage/directories?path=<relative>`: list child directories without following symlinks.
- `POST /api/storage/directories`: create a validated child directory.
- `POST /api/storage/migrations/preview`: validate and summarize a proposed target.
- `POST /api/storage/migrations`: create the migration after server-side recalculation.
- `GET /api/storage/migrations/current`: return persistent phase and progress.
- `POST /api/storage/migrations/{id}/retry`: resume a failed copy or cleanup phase.

Storage errors use stable codes for invalid path, symlink escape, not writable, active migration, target conflict, missing source, copy failure, commit failure, and cleanup failure.

### 5.2 Subscription APIs

- Extend `PATCH /api/subscriptions/{id}` with `initialization_strategy` and return reconciliation counts with the updated subscription.
- Add `POST /api/subscriptions/{id}/policy-preview` using the same planner in non-mutating mode.
- Keep download-task uniqueness enforcement in the database as the final concurrency guard.

### 5.3 Settings UI

The settings page adds a Download Storage card that:

- shows the mounted `/storage` state and active effective path;
- browses directories under `/storage`;
- creates a subdirectory;
- accepts a relative path directly;
- previews the effective path and migration file/byte totals;
- warns that unmanaged files are untouched;
- displays waiting, copying, committing, cleaning, completed, and failed phases;
- polls persistent migration progress and offers retry after failure;
- disables another location change while a migration is active.

### 5.4 Subscription UI

The current inline editor adds the initialization strategy. Before applying, it displays the server preview, for example:

> Create 42 MOBI tasks, convert 1 failed task, and retain 3 completed EPUB files.

After confirmation, the UI shows the actual reconciliation counts returned by apply and refreshes both subscriptions and downloads.

### 5.5 Download UI

Download rows display the stable error reason, safe detail, attempt count, and suggested action. Retry remains explicit for terminal failures. No signed URL is sent to the browser.

## 6. Service boundaries

Implementation should keep the following units independent:

- `StorageBoundary`: validate, resolve, list, create, and test directories under `/storage`.
- `StorageMigrationPlanner`: produce immutable per-file plans and conflict summaries.
- `StorageMigrationService`: coordinate pause, copy, commit, cleanup, and recovery.
- `SubscriptionPolicyPlanner`: calculate task reconciliation for preview and apply.
- `DownloadTransfer`: perform one validated transfer attempt and return typed failures.
- Existing workers: orchestrate persistence, retries, and wake-ups without embedding protocol parsing or path policy.

Each planner must be usable in tests without starting background workers.

## 7. Testing

### 7.1 Backend

- Download URL resolution, required transfer header, redirect validation, first-request behavior, valid resume, ignored Range fallback, malformed range, non-file response, and every error mapping.
- No diagnostic or serialized API response contains cookies or signed query strings.
- Storage path traversal, absolute paths, Windows-like paths, symlink components, directory creation, and writability checks.
- Empty migration, same-filesystem migration, cross-device-style copy behavior, same-size reuse, size conflict, copy crash recovery, commit recovery, cleanup recovery, and download pause/resume.
- Legacy `/downloads` path translation under the default mount.
- Every subscription policy transition, simultaneous content-type and format changes, duplicate target task reuse, failed-task reset, running-task retention, and activity counts.
- Migration and policy APIs enforce authentication, same-origin, and CSRF requirements.

### 7.2 Frontend

- Browse and create storage directories.
- Preview and confirm migration.
- Render all migration phases, conflicts, and retries.
- Preview and apply subscription policy changes.
- Render safe download errors and suggested actions.
- Preserve existing responsive and keyboard behavior.

### 7.3 Runtime

- Full backend and frontend test suites pass.
- Production frontend and Docker image build successfully.
- Health and readiness remain green during normal operation and storage migration.
- A controlled local fixture verifies files are not deleted before the active-root commit.
- The current failed live task is retried once and observed through a terminal state.

## 8. Rollout and operator documentation

- Add `KMOE_STORAGE_HOST_ROOT=./downloads` to `.env.example` and document Windows, Linux, and NAS Compose path examples.
- Document that host-root changes require container recreation and are not performed by the Web UI.
- Run database migrations before starting background services.
- Recover an active storage migration before download workers claim tasks.
- Preserve the existing default host directory on upgrade.
- Add a troubleshooting section for mount permissions, quota errors, transfer rejection, and migration conflicts.

## Acceptance criteria

- An administrator can browse or enter a subdirectory under `/storage`, preview a migration, start it, observe progress, and recover from interruption.
- No old managed file is deleted before every target copy has been verified and the active root is committed.
- Unmanaged files are never moved or deleted.
- Existing subscriptions can edit content types, format, and initialization strategy with an accurate preview and deterministic task reconciliation.
- Switching to `backfill` creates missing historical tasks without duplicates.
- Format changes follow the approved pending, failed, running, and completed task rules.
- The current unexplained download failure either completes or becomes a precise actionable upstream error.
- Secrets and signed URLs do not appear in logs, database errors, API responses, or the browser.
