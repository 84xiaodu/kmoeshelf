# Current implementation handoff

- Updated: 2026-08-16
- Branch: `main`
- Baseline commit: `84b596b`
- Active phase: Phase 4 — download worker and safe storage

## Completed

- Design specification committed as `d09eb9f`.
- Implementation plan committed as `56e0053`.
- FastAPI application factory, environment validation, Alembic migration, SQLite setup, administrator initialization/login/logout, Session/CSRF protection, health checks, Dockerfile and Compose committed as `e980ec8`.
- Kmoe stable schemas/errors, current mirror list, ordered failover, non-replayed POST, strict current volume JSON parser, format-specific sizes, comics/subscriptions/remote-item/task models, migration, initialization and refresh services committed as `35559aa`.
- Current/legacy login endpoint detection, one-shot password POST, same-mirror `/my.php` validation, HKDF-derived Fernet cookie encryption, single-account credential persistence and administrator-protected Kmoe login/status APIs committed as `4729fe4`.
- Sanitized search/detail fixtures, escape-aware JavaScript call parsing, trusted detail-path normalization, safe description text extraction, credential-backed search/detail APIs, and strict authenticated `/data_book.php` flow committed as `36106cf`.
- Subscription create/list/edit/pause/resume/delete APIs, explicit pending-task cancellation choice, persistent check batches, atomic SQLite task claiming, APScheduler six-hour checks, adjustable interval, manual checks, idempotent discovery and restart recovery committed as `290d820`.
- Strict `/getdownurl.php` format/line mapping, quota/error parsing, HTTPS/public-host validation, cross-platform path sanitization, `.part` integrity checks and atomic no-clobber final promotion committed as `84b596b`.
- File-based subagent memory protocol is defined in `AGENTS.md` and `docs/handoffs/README.md`; research and no-context verification handoffs prove it works without inherited chat context.
- Verification at `84b596b`: 32 tests passed with `.venv/bin/python -m pytest -q -s`; migration chain through `20260816_04`, model/migration drift check, Python compilation and `git diff --check` passed. Compose syntax previously passed at `e980ec8`.

## Active work

- Phase 2 target is complete: administrator can connect Kmoe, search, and fetch standardized comic details through mock-tested API contracts.
- Phase 3 target is complete: subscription management and persistent scheduled/manual checks are available through administrator APIs.
- Phase 4 is active: URL resolution and safe storage primitives are complete; worker lifecycle, transfer/resume, retry/cancel/recovery and download APIs remain.
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

1. Add a fixed `library_dir` to Comic and retry/cancel timestamps to DownloadTask through a migration.
2. Implement atomic pending-task claiming, streaming transfer to `.part`, strict redirect/length checks and final promotion.
3. Add bounded retry/backoff, cooperative cancellation, authentication/quota pausing and startup recovery.
4. Expose task list/filter/cancel/retry APIs and a throttled event stream or polling-compatible status contract.
5. Then build the React management UI over the completed APIs.
