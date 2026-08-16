# Current implementation handoff

- Updated: 2026-08-16
- Branch: `main`
- Baseline commit: `35559aa`
- Active phase: Phase 2 — Kmoe adapter, then subscription domain

## Completed

- Design specification committed as `d09eb9f`.
- Implementation plan committed as `56e0053`.
- FastAPI application factory, environment validation, Alembic migration, SQLite setup, administrator initialization/login/logout, Session/CSRF protection, health checks, Dockerfile and Compose committed as `e980ec8`.
- Kmoe stable schemas/errors, current mirror list, ordered failover, non-replayed POST, strict current volume JSON parser, format-specific sizes, comics/subscriptions/remote-item/task models, migration, initialization and refresh services committed as `35559aa`.
- File-based subagent memory protocol is defined in `AGENTS.md` and `docs/handoffs/README.md`; research and no-context verification handoffs prove it works without inherited chat context.
- Verification at `35559aa`: 16 tests passed with `.venv/bin/python -m pytest -q -s`; model/migration drift check, Python compilation and `git diff --check` passed. Compose syntax previously passed at `e980ec8`.

## Active work

- Phase 2 remains incomplete: Kmoe login/session persistence, search parser, detail parser and authenticated Kmoe API routes are not implemented.
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

1. Implement `/login_act.php` response parsing and `/my.php` validation with a mock transport test.
2. Add authenticated encryption and persistence for the minimal Kmoe cookie jar; never persist the password.
3. Expose administrator-protected Kmoe login/status API routes.
4. Implement search/detail extraction, including `data_book("hash")` discovery and strict `/data_book.php` parsing.
5. Then add scheduler and subscription API routes around the already-tested data services.
