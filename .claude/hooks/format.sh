#!/bin/sh
# PostToolUse: format + lint-fix edited Python files. Never blocks.
f=$(jq -r '.tool_input.file_path // empty')
case "$f" in *.py) uvx -q ruff format "$f" >/dev/null 2>&1; uvx -q ruff check --fix -q "$f" >&2 || true ;; esac
exit 0
