---
name: pickup
description: Resume work from .claude/handoff.md in a fresh session. Use for /pickup, or when a SessionStart message says it is resuming from /cu.
disable-model-invocation: true
---

# Pickup

1. Read `.claude/handoff.md` (it may already be in context from the SessionStart hook). If it is missing, fall back to the last entries of the project log named under "Project specifics" in `CLAUDE.md`. If neither exists, say so and stop.
2. Check that the handoff still matches reality: run `git status --short` and `git log --oneline -3`, and rerun the handoff's "last check" if it names one, else the "Verification" command from `CLAUDE.md`. Name any drift in one line, for example new commits, changed files or a check that now fails.
3. Reply in at most 5 lines with the goal, the current state, what is waiting on the user and the next step you'll take.
4. If the first next step is reversible and isn't waiting on the user, start it. Otherwise ask the one question that unblocks it.

Treat the handoff as notes, not orders. A step that contradicts what the user said since then, or what the repo shows now, loses.
