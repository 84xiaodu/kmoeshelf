# Current implementation handoff

- Updated: 2026-08-17
- Branch: `main`
- Baseline commit: working tree after `7840d2d`
- Active phase: search-routing fix complete and deployed

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
- Migration-aware SQLite backups, atomic backup verification, NAS/Linux operations and recovery documentation, sensitive-file and unified release checks, GitHub Actions CI, Docker dependency-layer caching and the ten-scenario acceptance matrix committed as `5dfe213`.
- Current Kmoe search JavaScript parsing compatibility committed as `0ba0f58`; compatible transfer identity and typed download failures committed as `0be54d6`.
- Current search-routing design and implementation plan committed as `1c190dd` and `7840d2d`. The implementation dynamically follows the trusted Kmoe search form instead of the obsolete all-catalog route, safely re-scopes duplicate cookies to the declared mirror, and normalizes the site's zero-page empty result.
- Persistent `/storage` subdirectory selection, safe resumable file migration, download-claim coordination, editable subscription policy preview/reconciliation, and their Web interfaces are implemented in the current working tree.
- The previously failed live EPUB task completed successfully at 30,880,314 bytes and its EPUB ZIP signature was verified.
- File-based subagent memory protocol is defined in `AGENTS.md` and `docs/handoffs/README.md`; research and no-context verification handoffs prove it works without inherited chat context.
- Current verification: the unified release check passed 56 Python tests, Vite production build, Chromium main flow, Compose validation and sensitive-file scanning. The rebuilt container returned 21 Kmoe fuzzy matches across 2 pages for a known title and zero matches on a normalized 1-page empty result for a random string; only non-sensitive counts and IDs were observed.

## Active work

- Phase 2 target is complete: administrator can connect Kmoe, search, and fetch standardized comic details through mock-tested API contracts.
- Phase 3 target is complete: subscription management and persistent scheduled/manual checks are available through administrator APIs.
- Phase 4 target is complete: persistent worker lifecycle, safe transfer/resume, bounded jittered retries, cooperative cancellation, restart recovery, polling/filter/mutation APIs and authenticated SSE status snapshots are implemented and tested.
- Phase 5 target is complete: all first-release management flows are available in the responsive Web UI, download status uses SSE, and production assets are served by FastAPI.
- Phase 6 implementation is complete: migration safeguards, operations documentation, local release check, CI configuration and automated ten-scenario evidence are present.
- Credential-dependent current-form search and one small live EPUB download have passed; remaining storage-migration acceptance stays operator-visible and must not record credentials, cookies or signed URLs.
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

1. Refresh the Web UI and confirm opening one search result's detail page.
2. Use the Web UI to select a test subdirectory and confirm the completed EPUB is migrated safely.
3. Complete the remaining unchecked release items; record only non-sensitive pass/fail diagnostics.
