#!/bin/sh
# SessionStart(clear): after /cu, inject the handoff into the fresh context once. Stdout becomes context.
# /cu writes the path of the project it worked in to ~/.claude/handoff.pending. That project can sit below the
# folder the session started in (a workspace root). The marker lives outside every repo, so a cloned repo can't
# plant a handoff that gets injected here.
m="$HOME/.claude/handoff.pending"
[ -f "$m" ] || exit 0
# Armed by a /cu more than an hour ago and never cleared: stale, drop it so a later /clear loads nothing.
[ -n "$(find "$m" -mmin -60)" ] || { rm -f "$m"; exit 0; }
d=$(head -n 1 "$m")
p=$(cd "$CLAUDE_PROJECT_DIR" && pwd -P) || exit 0
# Another session's project: leave the marker for that one.
case "$d/" in "$p"/*) ;; *) exit 0 ;; esac
[ -f "$d/.claude/handoff.md" ] || { rm -f "$m"; exit 0; }
rm -f "$m"
if [ "$d" = "$p" ]; then
  printf 'Resuming from /cu. Follow .claude/skills/pickup/SKILL.md with this handoff:\n\n'
else
  printf 'Resuming from /cu in %s. Work in that project (cd there first) and follow its .claude/skills/pickup/SKILL.md with this handoff:\n\n' "$d"
fi
cat "$d/.claude/handoff.md"
