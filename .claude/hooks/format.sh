#!/bin/sh
# PostToolUse: format + lint-fix an edited Python file, but only in a project that configures ruff
# (ruff.toml, .ruff.toml or [tool.ruff] in pyproject.toml at the project root). Without a config, ruff's
# defaults would reflow every file the agent touches, so the hook does nothing. Never blocks.
f=$(jq -r '.tool_input.file_path // empty')
case "$f" in *.py) ;; *) exit 0 ;; esac
d="${CLAUDE_PROJECT_DIR:-.}"
[ -f "$d/ruff.toml" ] || [ -f "$d/.ruff.toml" ] || grep -q '^\[tool\.ruff' "$d/pyproject.toml" 2>/dev/null || exit 0
uvx -q ruff format "$f" >/dev/null 2>&1
uvx -q ruff check --fix -q "$f" >&2 || true
exit 0
