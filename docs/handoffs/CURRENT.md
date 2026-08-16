# Current implementation handoff

- Updated: 2026-08-16
- Branch: `main`
- Baseline commit: `4729fe4`
- Active phase: Phase 2 — Kmoe adapter, then subscription domain

## Completed

- Design specification committed as `d09eb9f`.
- Implementation plan committed as `56e0053`.
- FastAPI application factory, environment validation, Alembic migration, SQLite setup, administrator initialization/login/logout, Session/CSRF protection, health checks, Dockerfile and Compose committed as `e980ec8`.
- Kmoe stable schemas/errors, current mirror list, ordered failover, non-replayed POST, strict current volume JSON parser, format-specific sizes, comics/subscriptions/remote-item/task models, migration, initialization and refresh services committed as `35559aa`.
- Current/legacy login endpoint detection, one-shot password POST, same-mirror `/my.php` validation, HKDF-derived Fernet cookie encryption, single-account credential persistence and administrator-protected Kmoe login/status APIs committed as `4729fe4`.
- File-based subagent memory protocol is defined in `AGENTS.md` and `docs/handoffs/README.md`; research and no-context verification handoffs prove it works without inherited chat context.
- Verification at `4729fe4`: 22 tests passed with `.venv/bin/python -m pytest -q -s`; migration chain, model/migration drift check, Python compilation and `git diff --check` passed. Compose syntax previously passed at `e980ec8`.

## Active work

- Phase 2 remains incomplete: search parsing, detail metadata/hash discovery, authenticated credential restoration and search/detail API routes are not implemented.
- A Phase 3 data slice is complete, but scheduler and subscription API routes are not implemented.
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

1. Add a credential-backed Kmoe client helper that restores the encrypted cookie jar and rejects invalid/expired credentials.
2. Implement search result extraction from sanitized fixtures and expose an administrator-protected search API.
3. Implement detail metadata and `data_book("hash")` discovery, then fetch and strictly parse `/data_book.php` without accepting the unauthenticated empty sentinel.
4. Add mock-transport API tests for search/detail, mirror failover and structured authentication/site-change failures.
5. Then add scheduler and subscription API routes around the already-tested data services.
