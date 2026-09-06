# First lean-runtime and CI efficiency patch handoff

- Baseline commit: `8f21b0830430cb7205ab079f2f5308b1ef49ac07`
- Scope owned: `src/kmoe_subscriptions/services/downloads.py`, `src/kmoe_subscriptions/api/downloads.py`, `tests/test_download_worker.py`, `tests/test_subscription_api.py`, `frontend/src/api.ts`, `frontend/src/types.ts`, `frontend/src/pages/Dashboard.tsx`, `frontend/src/pages/Downloads.tsx`, `frontend/tests/app.spec.ts`, `.github/workflows/ci.yml`, `.github/workflows/publish-image.yml`, `docs/handoffs/CURRENT.md`, and this handoff
- Status: complete

## Decisions and facts

- `_transfer` now gates intermediate database progress writes only on one elapsed second; throughput no longer triggers writes at each MiB. The final `_progress` call remains unconditional after a successful response stream.
- The first-release download snapshot has a fixed `RECENT_TASK_LIMIT = 100`. Its default REST/SSE view contains all running tasks plus the 100 newest non-running tasks, ordered newest first. A selected status is sent to both REST and SSE; completed history stays bounded while pending, running, failed, and cancelled views remain unbounded so their actions are accessible.
- Download snapshots expose exact database-grouped counts for all five task statuses. Dashboard and Downloads consume those counts rather than deriving totals from the bounded task array.
- Task detail, cancel, and retry routes remain ID-based and unchanged. Existing cancel/retry integration coverage passes with the snapshot response.
- CI invokes the existing mode-`100644` sensitive-file script through Bash and checks out depth 2 before using `HEAD^`.
- CI's container job runs only for pull requests. The publish workflow runs only for pushes to `main` and always pushes, yielding one Docker build per PR and one build/push on `main`.

## Changes

- `src/kmoe_subscriptions/services/downloads.py`: removed the byte-volume progress trigger and made the final progress write unconditional.
- `src/kmoe_subscriptions/api/downloads.py`: added bounded task snapshots and exact grouped status counts for REST and SSE; SSE accepts the REST status filter and only completed filtered history is bounded.
- `tests/test_download_worker.py`: added the focused high-throughput progress-write regression.
- `tests/test_subscription_api.py`: added bounded-history/all-running/exact-count coverage, proves more than 100 failed tasks remain retrievable by status, and adapted existing snapshot/SSE/cancel/retry assertions.
- `frontend/src/types.ts`, `frontend/src/api.ts`: reused the download task type inside a typed snapshot envelope.
- `frontend/src/pages/Dashboard.tsx`, `frontend/src/pages/Downloads.tsx`: consume bounded tasks and exact counts; Downloads reloads REST and reconnects SSE with each selected status, and ignores an older REST result after receiving a valid SSE event.
- `frontend/tests/app.spec.ts`: verifies Dashboard exact counts, actionable status retrieval, and SSE winning over a delayed stale REST snapshot; updated the existing API fixture.
- `.github/workflows/ci.yml`, `.github/workflows/publish-image.yml`: fixed security execution/depth and split image-build events.
- `docs/handoffs/CURRENT.md`: merged verified implementation and test state.

## Verification

### RED/GREEN: progress write throttling

- RED: `.venv/bin/python -m pytest -q -s tests/test_download_worker.py::test_transfer_throttles_progress_writes_by_time`
  - Result: expected failure; updates were `[1048576, 2097152, 3145728]` instead of only final `[3145728]`.
- GREEN: `.venv/bin/python -m pytest -q -s tests/test_download_worker.py::test_transfer_throttles_progress_writes_by_time tests/test_download_worker.py::test_transfer_does_not_query_cancellation_for_every_chunk`
  - Result: `2 passed in 0.73s`.

### RED/GREEN: bounded backend snapshot

- RED: `.venv/bin/python -m pytest -q -s tests/test_subscription_api.py::test_download_snapshot_bounds_history_and_keeps_exact_counts`
  - Result: expected failure; the old unbounded list caused `TypeError: list indices must be integers or slices, not str` at `snapshot["tasks"]`.
- GREEN: `.venv/bin/python -m pytest -q -s tests/test_subscription_api.py::test_download_snapshot_bounds_history_and_keeps_exact_counts`
  - Result: `1 passed, 2 warnings in 1.00s`.

### RED/GREEN: Dashboard exact counts

- Environment setup: `npm --prefix frontend ci --no-audit --no-fund` installed 27 packages; `npx --prefix frontend playwright install chromium` installed the required browser.
- RED: `npm --prefix frontend test -- --grep '仪表盘使用完整任务计数'`
  - Result: expected failure after browser installation; Vite reported `TypeError: downloads.filter is not a function`, and the exact-count assertion could not find the statistic.
- GREEN: `npm --prefix frontend test -- --grep '仪表盘使用完整任务计数'`
  - Result: `1 passed (2.6s)`.

### RED/GREEN: actionable status views

- RED: `npm --prefix frontend test -- --grep '下载状态筛选取回默认快照外的失败任务并提供重试'`
  - Result: expected failure; selecting Failed did not retrieve the task absent from the default snapshot, so its heading and Retry action were missing.
- RED: `.venv/bin/python -m pytest -q -s tests/test_subscription_api.py::test_download_snapshot_bounds_history_and_keeps_exact_counts`
  - Result: expected failure; the failed status response returned only 100 of 105 failed tasks.
- GREEN: both focused commands passed after status was applied to REST/SSE and the limit was restricted to completed filtered history.

### Additional evidence

- RED: `npm --prefix frontend test -- --grep '较慢的 REST 快照不会覆盖较新的下载事件'`
  - Result: expected failure; the delayed REST response replaced the newer SSE task (`1 failed`).
- GREEN: the same focused command passed after guarding the REST update (`1 passed`).

- `.venv/bin/python -m pytest -q -s tests/test_download_worker.py tests/test_subscription_api.py`
  - Result: `7 passed, 2 warnings in 1.86s`.
- `npm --prefix frontend run build`
  - Result: TypeScript and Vite build passed.
- `npm --prefix frontend test`
  - Result: `4 passed (6.1s)`.
- `.venv/bin/python -m pytest -q -s`
  - Result: `60 passed, 2 warnings in 5.46s`.
- `bash scripts/check-sensitive-files.sh`
  - Result: passed.
- A temporary depth-2 fetch followed by `git diff --check HEAD^ HEAD`
  - Result: exit 0, confirming the shallow-checkout fix locally.

## Unresolved

- GitHub-hosted event execution cannot be proven locally. Confirm that the next PR runs only CI's image build and the next `main` push runs only the publishing image build.
- Tests ran with the available Python 3.13 environment; CI remains configured for Python 3.12.

## Next action

Open a pull request without committing from this session only after review, then verify the security job and single PR image build in GitHub Actions.
