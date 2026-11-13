#!/bin/sh
# SessionStart (startup, resume, clear, compact): load the pote-tail working style into
# every session, so it is on without being invoked. Stdout becomes context.
f="$CLAUDE_PROJECT_DIR/.claude/skills/pote-tail/SKILL.md"
[ -f "$f" ] || exit 0
printf 'The pote-tail working style is active for this session (level full; the user can switch with /pote-tail lite|ultra|off). Its rules:\n\n'
awk 'n < 2 && /^---$/ { n++; next } n >= 2' "$f"
exit 0
