# Current implementation handoff

- Updated: 2026-08-17
- Branch: `main`
- Baseline commit: `8aad3a5`
- Active phase: Phase 6 — operations and release acceptance

## Completed

- Design specification committed as `d09eb9f`.
- Implementation plan committed as `56e0053`.
- FastAPI application factory, environment validation, Alembic migration, SQLite setup, administrator initialization/login/logout, Session/CSRF protection, health checks, Dockerfile and Compose committed as `e980ec8`.
- Kmoe stable schemas/errors, current mirror list, ordered failover, non-replayed POST, strict current volume JSON parser, format-specific sizes, comics/subscriptions/remote-item/task models, migration, initialization and refresh services committed as `35559aa`.
- Current/legacy login endpoint detection, one-shot password POST, same-mirror `/my.php` validation, HKDF-derived Fernet cookie encryption, single-account credential persistence and administrator-protected Kmoe login/status APIs committed as `4729fe4`.
- Sanitized search/detail fixtures, escape-aware JavaScript call parsing, trusted detail-path normalization, safe description text extraction, credential-backed search/detail APIs, and strict authenticated `/data_book.php` flow committed as `36106cf`.
- Subscription create/list/edit/pause/resume/delete APIs, explicit pending-task cancellation choice, persistent check batches, atomic SQLite task claiming, APScheduler six-hour checks, adjustable interval, manual checks, idempotent discovery and restart recovery committed as `290d820`.
- Strict `/getdownurl.php` format/line mapping, quota/error parsing, HTTPS/public-host validation, cross-platform path sanitization, `.part` integrity checks and atomic no-clobber final promotion committed as `84b596b`.
- Stable per-comic library directories plus persistent task retry, cancellation, start and completion fields with migration `20260816_05` committed as `0911a93`.
- Atomic download claiming, startup recovery, validated resume/redirect transfer, throttled progress writes, safe failure mapping, bounded retry state, cooperative cancellation, task polling/filter/cancel/retry APIs and immediate worker wakeups committed as `88721a4`.
- Authenticated SSE download snapshots and keepalives committed as `52879e3`; bounded exponential retry jitter committed as `9451ec8`.
- Responsive React/TypeScript management UI for setup/login, dashboard, Kmoe login, search/detail, subscription management, SSE downloads and settings; full runtime settings and administrator password change APIs; FastAPI static hosting; Playwright main-flow coverage; and Docker multi-stage frontend build committed as `8aad3a5`.
- Installed-wheel migration discovery now prefers the runtime project root, fixing Docker startup while retaining source-tree tests.
- File-based subagent memory protocol is defined in `AGENTS.md` and `docs/handoffs/README.md`; research and no-context verification handoffs prove it works without inherited chat context.
- Verification at `8aad3a5`: 36 Python tests passed with `.venv/bin/python -m pytest -q -s`; `npm --prefix frontend run build` and the Chromium Playwright main flow passed; `docker build -t kmoe-subscriptions:phase5 .` passed; the built container returned `{"status":"ok"}` from `/health/ready` and served the hashed React assets from `/`.

## Active work

- Phase 2 target is complete: administrator can connect Kmoe, search, and fetch standardized comic details through mock-tested API contracts.
- Phase 3 target is complete: subscription management and persistent scheduled/manual checks are available through administrator APIs.
- Phase 4 target is complete: persistent worker lifecycle, safe transfer/resume, bounded jittered retries, cooperative cancellation, restart recovery, polling/filter/mutation APIs and authenticated SSE status snapshots are implemented and tested.
- Phase 5 target is complete: all first-release management flows are available in the responsive Web UI, download status uses SSE, and production assets are served by FastAPI.
- Phase 6 is active: operations documentation, CI, backup-before-risky-migration behavior and the final ten-scenario release checklist remain.
- No subagent currently owns application files.

## Accepted decisions

- One application container; SQLite is the persistent source of truth.
- Kmoe protocol details stay behind a replaceable adapter.
- Use stable remote comic/item IDs for deduplication, never titles.
- First release has one administrator and one Kmoe account.
- Keep Uvicorn base package only; its `standard` extras are not needed yet.
- Current mirror candidates include `mox.moe`, `kxo.moe`, `kxx.moe`, `kzz.moe`, and `koz.moe`.
- Password-bearing login POST is sent once to the active mirror and is never replayed after an ambiguous network failure.
- Current detail volume data comes from `/data_book.php?h=...`; the unauthenticated HTTP-200 empty sentinel is an authentication failure, never a valid baseline.
- Use ebook pages at `voldata[7]`; preserve MOBI/EPUB catalog sizes separately from indexes 9 and 11.
- Resolve downloads through `/getdownurl.php`; do not construct `/dl/` URLs directly.

## Known environment detail

- The host Python is 3.14.6 and Node is 26.3.0.
- Pytest capture cleanup fails in this desktop environment, so use `-s` when running tests.
- The in-process `TestClient` currently emits one third-party Starlette deprecation warning; application tests still pass.

## Next actions

1. Add database backup-before-risky-migration behavior and focused recovery tests.
2. Finish NAS/Linux deployment, reverse-proxy HTTPS, backup/restore and upgrade documentation.
3. Add CI for Python, frontend build/Playwright, Docker and sensitive-data checks.
4. Execute and record the design document's ten release acceptance scenarios.
