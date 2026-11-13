---
name: cu
description: Clear and resume ("clear-up"). Writes the handoff and arms an automatic pickup for the next /clear. Use for /cu.
disable-model-invocation: true
---

# /cu

A command can't run `/clear` itself, so /cu prepares everything and the user types `/clear`.

1. Follow `.claude/skills/handoff/SKILL.md` in full.
2. Run `touch .claude/handoff.pending`. On the next `/clear`, the SessionStart hook (`.claude/hooks/pickup-on-clear.sh`) loads the handoff into the fresh context once, deletes the marker and starts the pickup.
3. Reply with exactly one line: `Handoff written. Type /clear to continue in a fresh context.`
