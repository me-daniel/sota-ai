#!/bin/sh
# SessionStart(clear): after /cu, inject the handoff into the fresh context once. Stdout becomes context.
cd "$CLAUDE_PROJECT_DIR" || exit 0
[ -f .claude/handoff.pending ] && [ -f .claude/handoff.md ] || exit 0
rm -f .claude/handoff.pending
printf 'Resuming from /cu. Follow .claude/skills/pickup/SKILL.md with this handoff:\n\n'
cat .claude/handoff.md
