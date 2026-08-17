# Storage, Subscription Policy, and Download Reliability Implementation Plan

Date: 2026-08-17
Design: `docs/superpowers/specs/2026-08-17-storage-policy-download-reliability-design.md`

## Implementation principles

- Keep Kmoe URL resolution, required headers, and upstream error interpretation inside `src/kmoe_subscriptions/kmoe/`.
- Keep `/storage` as the immutable trust boundary and store only a relative active subpath in SQLite.
- Keep SQLite as the authoritative state for download pauses, migration recovery, and policy reconciliation.
- Add a failing test before each non-trivial behavior, then make the smallest implementation pass.
- Preserve the already deployed search-parser fix as an independent commit.
- Never persist or print cookies, credentials, signed URLs, query strings, or upstream HTML.
- Do not add Redis, Celery, WebSocket, a component library, or Docker-socket access.

## Verified live failure

The current failed EPUB task obtains a valid signed HTTPS URL from Kmoe, but the transfer host `dl.kmoe9.com` returns HTTP 403 before any bytes are written when the client uses HTTPX's default User-Agent. With the same `X-Km-From: kb_http_down` header and the reference client's explicit User-Agent, the transfer returns HTTP 200 with `application/epub+zip` and a non-zero first chunk.

The first implementation slice must therefore make the transfer User-Agent explicit and Kmoe-compatible. It must also retain safe status diagnostics so a future rejection does not collapse into a generic network error.

## Phase 0: Preserve the search compatibility fix

Files:

- `src/kmoe_subscriptions/kmoe/parser.py`
- `tests/fixtures/kmoe/search_results_current.html`
- `tests/test_kmoe_parser.py`

Tasks:

1. Re-run parser and full backend tests.
2. Confirm the parser ignores function declarations and empty initialization calls.
3. Confirm it supports only string-literal concatenation and rejects dynamic JavaScript operands.
4. Commit these three files without mixing storage or download changes.

Verification:

```bash
.venv/bin/python -m pytest -q -s tests/test_kmoe_parser.py
.venv/bin/python -m pytest -q -s
git diff --check
```

## Phase 1: Fix live transfers and expose typed failures

Files:

- `src/kmoe_subscriptions/kmoe/downloads.py`
- `src/kmoe_subscriptions/kmoe/errors.py`
- `src/kmoe_subscriptions/services/downloads.py`
- `src/kmoe_subscriptions/main.py`
- `src/kmoe_subscriptions/api/downloads.py`
- `tests/test_kmoe_downloads.py`
- `tests/test_download_worker.py`

Tasks:

1. Add tests proving the transfer factory sends both an explicit Kmoe-compatible User-Agent and `X-Km-From: kb_http_down`.
2. Centralize transfer headers in the Kmoe adapter so application startup does not duplicate protocol constants.
3. Add typed transfer failures for forbidden, expired URL, rate limit, timeout, server error, non-file response, and invalid range.
4. Change the transfer loop to raise those types with only safe stage, status, and host information.
5. Map deterministic failures to stable task error codes and retry only transient classes.
6. Store safe diagnostics and emit a warning for terminal failures without including URL path, query, response body, or Cookie.
7. Preserve first-request no-Range behavior, valid resume, and `200` restart fallback.
8. Add API serialization tests for the new stable error codes.

Verification:

```bash
.venv/bin/python -m pytest -q -s tests/test_kmoe_downloads.py tests/test_download_worker.py
```

Commit boundary: transfer protocol, error taxonomy, worker mapping, and tests.

## Phase 2: Add the storage trust boundary and persistent schema

Files:

- `src/kmoe_subscriptions/config.py`
- `src/kmoe_subscriptions/models.py`
- `src/kmoe_subscriptions/storage.py`
- `migrations/versions/20260817_06_storage_migrations.py`
- `tests/test_storage.py`
- `tests/test_migrations.py`
- `compose.yaml`
- `.env.example`

Tasks:

1. Change the production container download root from `/downloads` to `/storage` while retaining the internal `Settings.download_dir` name for test and API compatibility.
2. Add `AppSetting.download_subpath` with an empty default.
3. Add `StorageMigration` and `StorageMigrationFile` models, indexes, foreign keys, uniqueness, phases, progress, failure fields, and timestamps.
4. Add an Alembic migration that creates the new schema and translates legacy completed `/downloads/...` paths to `/storage/...`; clear non-completed cached paths.
5. Implement `StorageBoundary` for relative-path normalization, component-wise no-symlink resolution, listing, directory creation, effective-root calculation, and exclusive writability probes.
6. Update `download_paths` to accept the active effective root while preserving filename sanitization and root containment.
7. Add traversal, absolute Windows path, symlink, collision, create-directory, and writable-probe tests.
8. Update Compose to mount `${KMOE_STORAGE_HOST_ROOT:-./downloads}:/storage` and pass `KMOE_DOWNLOAD_DIR=/storage`.

Verification:

```bash
.venv/bin/python -m pytest -q -s tests/test_storage.py tests/test_migrations.py
docker compose config
```

Commit boundary: models, migration, storage boundary, Compose compatibility, and tests.

## Phase 3: Implement resumable storage migration and APIs

Files:

- `src/kmoe_subscriptions/services/storage_migrations.py`
- `src/kmoe_subscriptions/api/storage.py`
- `src/kmoe_subscriptions/main.py`
- `src/kmoe_subscriptions/services/downloads.py`
- `tests/test_storage_migrations.py`
- `tests/test_storage_api.py`

Tasks:

1. Implement a pure `StorageMigrationPlanner` that previews files, bytes, missing sources, and conflicts.
2. Implement creation that persists only the requested source/target before pausing claims.
3. Make download claiming atomically skip work while a migration is active.
4. Wait for already-running downloads to finish, then persist the final per-file plan so late completions are included.
5. Copy each source to a unique `.migrating` sibling, flush, verify size, and atomically promote it.
6. Reuse same-size targets and fail on different-size targets without changing the active root.
7. Commit active subpath and completed task paths in one transaction; clear cached paths for non-completed tasks.
8. Delete only committed source files and application-created empty directories.
9. Recover pending, copy, commit, and cleanup phases at startup before download claims resume.
10. Add storage status, directory listing/creation, migration preview/start/status/retry APIs with session, same-origin, and CSRF protection.
11. Add tests for empty migration, running-download drain, late completion inclusion, cross-device-style copy, conflict, restart before commit, restart after commit, cleanup retry, and sensitive-path filtering.

Verification:

```bash
.venv/bin/python -m pytest -q -s tests/test_storage_migrations.py tests/test_storage_api.py tests/test_download_worker.py
```

Commit boundary: persistent migration service, coordination, APIs, recovery, and tests.

## Phase 4: Implement subscription policy preview and reconciliation

Files:

- `src/kmoe_subscriptions/services/subscription_policy.py`
- `src/kmoe_subscriptions/api/subscriptions.py`
- `src/kmoe_subscriptions/models.py`
- `tests/test_subscriptions.py`
- `tests/test_subscription_api.py`

Tasks:

1. Implement a pure planner that calculates created, converted, reused, cancelled, and retained task counts.
2. Add `initialization_strategy` to `SubscriptionEdit`.
3. Add a non-mutating policy-preview endpoint.
4. Recalculate and apply the plan transactionally in PATCH rather than trusting preview counts.
5. On `future_only` to `backfill`, enqueue every missing selected current-format item.
6. On format change, convert selected pending and failed tasks; reset failed retry state and paths.
7. Reuse an existing new-format task and cancel the colliding old pending or failed task.
8. Retain running tasks, completed old-format files, removed-type tasks, and already queued backfill tasks when switching to `future_only`.
9. Wake the download worker when reconciliation creates or requeues work.
10. Write an activity event containing only entity IDs and aggregate counts.
11. Cover every approved transition, simultaneous field changes, duplicate target tasks, and preview/apply recalculation.

Verification:

```bash
.venv/bin/python -m pytest -q -s tests/test_subscriptions.py tests/test_subscription_api.py
```

Commit boundary: policy planner, API, reconciliation, activity summary, and tests.

## Phase 5: Add the Web storage and policy experiences

Files:

- `frontend/src/types.ts`
- `frontend/src/api.ts`
- `frontend/src/pages/Settings.tsx`
- `frontend/src/pages/Subscriptions.tsx`
- `frontend/src/pages/Downloads.tsx`
- `frontend/src/styles.css`
- `frontend/tests/app.spec.ts`

Tasks:

1. Add typed storage status, directory, migration preview/progress, and policy preview/reconciliation responses.
2. Add a Download Storage card that browses and creates directories, accepts a relative path, previews the effective path, and starts migration after confirmation.
3. Poll only while a migration is active and render waiting, copying, committing, cleaning, completed, and failed states.
4. Disable a second location change during migration and provide retry for a failed phase.
5. Extend the subscription editor with `future_only` / `backfill`.
6. Show policy impact before apply and actual reconciliation counts after save.
7. Render precise safe download errors and suggested actions.
8. Add responsive and keyboard-visible styling without a component library.
9. Extend Playwright mocks and cover storage migration, policy preview/apply, and typed download errors.

Verification:

```bash
npm --prefix frontend test
npm --prefix frontend run build
```

Commit boundary: frontend types, API client, settings/subscription/download UI, styles, and browser tests.

## Phase 6: Integration, operations, and live acceptance

Files:

- `README.md`
- `docs/operations.md`
- `docs/release-checklist.md`
- `docs/handoffs/CURRENT.md`
- relevant fixture and integration tests discovered during acceptance

Tasks:

1. Document `KMOE_STORAGE_HOST_ROOT` examples for Windows, Linux, and NAS paths.
2. Document the distinction between deployment-time host mount and Web-managed subdirectory migration.
3. Document permission, conflict, quota, forbidden-transfer, and cleanup recovery steps.
4. Run the full backend suite, frontend tests/build, release check, Compose validation, and Docker build.
5. Rebuild and start the local service; verify readiness and persistent migration recovery.
6. Retry the current failed EPUB task once after the transfer-header fix.
7. Monitor it to completion or a precise non-generic upstream terminal condition.
8. Verify any completed file has non-zero size, EPUB content type/extension, and a path under the active `/storage` subdirectory.
9. Run the sensitive-data scan and inspect logs for signed URL, Cookie, or credential leakage.
10. Update the current handoff with exact non-sensitive evidence and remaining external limitations.

Verification:

```bash
.venv/bin/python -m pytest -q -s
npm --prefix frontend test
npm --prefix frontend run build
./scripts/release-check.sh
docker compose config
docker compose up -d --build
docker compose ps
curl -fsS http://localhost:8000/health/ready
git diff --check
```

## Final acceptance

- The current download no longer fails because of HTTPX's default User-Agent.
- Transfer failures expose a stable actionable reason without leaking signed URLs.
- The operator can choose and migrate to a subdirectory below the one host-mounted `/storage` root.
- Migration is restart-safe and never deletes unmanaged or unverified source files.
- Existing subscriptions can preview and apply content-type, format, and initialization-strategy changes.
- Approved task conversion and retention rules are enforced without duplicates.
- Backend, frontend, Docker, security scan, and live acceptance checks pass.
