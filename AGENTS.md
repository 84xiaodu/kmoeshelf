# Agent working agreement

## Start here

Before changing code, read these files in order:

1. `docs/superpowers/specs/2026-08-16-kmoe-subscription-service-design.md`
2. `docs/superpowers/plans/2026-08-16-kmoe-subscription-service-implementation.md`
3. `docs/handoffs/CURRENT.md`

Then inspect `git status --short` and the files named by the current task. The working tree is shared by all agents; preserve unrelated edits.

## Subagent memory handoff

- Give every subagent a bounded task and a unique file under `docs/handoffs/`.
- A subagent owns only the files named in its task. Research-only agents must not edit application code.
- Before finishing, the subagent writes a handoff using `docs/handoffs/README.md` and reports its path.
- The primary agent reads the handoff, verifies its evidence, and merges accepted facts into `docs/handoffs/CURRENT.md`.
- Do not treat chat memory as authoritative when a handoff or the worktree disagrees.
- Never put credentials, cookies, signed URLs, or unredacted upstream pages in a handoff.

## Project rules

- Keep Kmoe protocol details inside `src/kmoe_subscriptions/kmoe/`.
- Keep database migrations aligned with SQLAlchemy models.
- Add the smallest runnable test for non-trivial behavior.
- Do not add Redis, Celery, WebSocket, a UI component library, or multi-account support in the first release.
- Run `.venv/bin/python -m pytest -q -s` before handing off Python changes.

