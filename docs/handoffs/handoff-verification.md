# Memory handoff verification

- Baseline commit: `e980ec8`
- Scope owned: verification only; `docs/handoffs/handoff-verification.md` is the only file owned by this agent
- Status: complete

## Decisions and facts

### Current phase

- Phase 1 is the latest completed implementation phase. `docs/handoffs/CURRENT.md` records the application/authentication baseline at `e980ec8`, and the current full test run still passes the Phase 1 tests.
- Phase 2 is active but incomplete. The worktree now has adapter schemas, an HTTP failover client, volume JSON parsing, fixtures and unit tests under `src/kmoe_subscriptions/kmoe/` and `tests/`, but it does not have the planned Kmoe login/search/detail API route (`src/kmoe_subscriptions/api/kmoe.py` is absent, and `src/kmoe_subscriptions/main.py` includes only `auth_router`).
- A narrow Phase 3 slice is already in progress ahead of Phase 2 completion: `Comic`, `Subscription`, `RemoteItemRecord`, `DownloadTask` and `ActivityEvent`, migration `20260816_02`, plus `initialize_subscription`/`refresh_subscription` and their tests exist. Scheduler and subscription API files from the implementation plan are still absent.

### Research absorption

The priority conclusions in `docs/handoffs/kmoe-adapter-research.md` have been **partially and materially absorbed**:

- `src/kmoe_subscriptions/kmoe/client.py` includes `mox.moe` and `kxo.moe`, keeps ordered mirror promotion, does not replay POST across mirrors, and distinguishes authentication, rate limit, not-found and mirror exhaustion.
- `src/kmoe_subscriptions/kmoe/parser.py` rejects the observed unauthenticated HTTP-200 empty sentinel, validates `volcount`, rejects unknown content types, reads ebook page count from index 7, and preserves MOBI/EPUB sizes from indexes 9/11.
- `src/kmoe_subscriptions/kmoe/schemas.py`, `src/kmoe_subscriptions/models.py` and `migrations/versions/20260816_02_subscriptions.py` preserve format-specific sizes and use `(comic_id, content_type, remote_id)` as remote item identity. The model and migration names/types/constraints inspected for these new tables are aligned.
- `tests/test_kmoe_client.py`, `tests/test_kmoe_parser.py`, and the two minimized Kmoe fixtures exercise mirror promotion, non-replayed login POST, not-found/rate-limit distinction, format-specific indexes, known content types, and the unauthenticated empty sentinel.

The research has **not** been fully absorbed:

- No login flow, login-page endpoint detection, search parser, detail parser, `data_book("hash") -> /data_book.php` fetch, explicit legacy `/book_data.php` compatibility parser, session encryption/persistence, download-URL resolution, or Kmoe API layer exists yet.
- `KmoeClient` raises `RateLimited` immediately and does not honor `Retry-After`; it also still maps every 401/403 to `AuthenticationExpired`, although the research requires route/body-aware separation for content blocking and other 403 cases.
- Mirror validation rejects obvious paths but is not a strict HTTPS hostname/allowlist validation implementation.

### Still inconsistent or stale

- `docs/handoffs/CURRENT.md` is stale: it says the research subagent is active and that the next action is to read `kmoe-adapter-research.md`, while that handoff is now `Status: complete` and several conclusions are already implemented. The primary agent should merge verified facts into `CURRENT.md`.
- The implementation plan's Phase 2 goal (administrator-accessible Kmoe login, search and normalized detail) is not satisfied by the current passing tests; only lower-level client and volume parsing behavior is present.

## Changes

- Added `docs/handoffs/handoff-verification.md` as verification-only durable memory.
- No application code, migration, fixture, test, or existing handoff was modified.

## Verification

Files read in required order and then cross-checked:

```text
docs/superpowers/specs/2026-08-16-kmoe-subscription-service-design.md
docs/superpowers/plans/2026-08-16-kmoe-subscription-service-implementation.md
docs/handoffs/CURRENT.md
docs/handoffs/README.md
docs/handoffs/kmoe-adapter-research.md
```

Repository/code evidence commands:

```text
git status --short
git diff --stat
git diff -- src tests migrations docs/handoffs/CURRENT.md
rg --files src/kmoe_subscriptions/kmoe src/kmoe_subscriptions/services tests/fixtures tests | sort
sed -n ... src/kmoe_subscriptions/kmoe/{schemas,errors,client,parser}.py
sed -n ... src/kmoe_subscriptions/services/subscriptions.py
sed -n ... migrations/versions/20260816_02_subscriptions.py
sed -n ... tests/test_{kmoe_client,kmoe_parser,subscriptions}.py
rg -n "include_router|KmoeClient|parse_volume_data|initialize_subscription|refresh_subscription|login_act|data_book|disp_divinfo|getdownurl" src tests migrations
git rev-parse --short HEAD
# e980ec8
git diff --check
# success, no output
```

Required Python verification:

```text
.venv/bin/python -m pytest -q -s
# 15 passed, 1 warning in 10.59s
# Warning: the already-known Starlette TestClient/httpx deprecation warning.
```

## Unresolved

- There is no authenticated sanitized success fixture for `/data_book.php`; therefore valid empty-volume semantics remain deliberately rejected and unverified, matching the research handoff's warning.
- Current tests do not cover login/session persistence, search/detail parsing, `Retry-After`, route-aware 403 classification, legacy parsing, API authorization, scheduler behavior, or concurrent subscription refresh races.
- The worktree is intentionally dirty and shared. All application changes inspected here pre-existed this verification task and were left untouched.

## Next action

Update `docs/handoffs/CURRENT.md` with this verified state, then finish the smallest missing Phase 2 vertical slice: implement current `/login_act.php` login plus `/my.php` validation behind an authenticated Kmoe API route, with a local mock-transport test proving the password-bearing POST is never replayed to another mirror. After that, implement search/detail extraction and strict `/data_book.php` parsing before expanding Phase 3 scheduler/API work.
