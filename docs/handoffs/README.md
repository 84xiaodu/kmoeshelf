# Handoff format

Each agent handoff is durable project memory. Use a task-specific filename and include every section below.

```markdown
# <task> handoff

- Baseline commit: <hash>
- Scope owned: <files or research boundary>
- Status: complete | partial

## Decisions and facts

Only verified facts, with source file, URL, command, or test evidence.

## Changes

Files changed and why. Write `None` for research-only work.

## Verification

Exact commands and results.

## Unresolved

Unknowns, risks, or assumptions that the next agent must not mistake for facts.

## Next action

The smallest concrete continuation step.
```

Do not include secrets, cookies, signed URLs, or copied full upstream pages.

