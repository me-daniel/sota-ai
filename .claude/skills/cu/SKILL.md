---
name: cu
description: Clear and resume ("clear-up"). Writes the handoff and arms an automatic pickup for the next /clear. Use for /cu.
disable-model-invocation: true
---

# /cu

A command can't run `/clear` itself, so /cu prepares everything and the user types `/clear`.

1. Follow `.claude/skills/handoff/SKILL.md` in full.
2. From the root of the project whose handoff you just wrote, run `pwd -P > ~/.claude/handoff.pending`. On the next `/clear`, the SessionStart hook (`.claude/hooks/pickup-on-clear.sh`) loads that project's handoff into the fresh context once, deletes the marker and starts the pickup. This also works when the session started in a parent folder such as a workspace root.
3. Reply with exactly one line: `Handoff written. Type /clear to continue in a fresh context.`
