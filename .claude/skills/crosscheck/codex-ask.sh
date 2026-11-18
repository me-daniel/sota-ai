#!/bin/sh
# Ask Codex once, isolated: empty working dir, read-only sandbox, no user config or rules,
# stdin closed (codex exec waits forever on an open stdin), no API-key env.
# usage: codex-ask.sh <model|-> <prompt-file> <reply-file>    ("-" = Codex's default model)
# Writes Codex's final message to <reply-file>. Exit 1 if there is no completed turn or no reply.
set -eu
model=$1 prompt=$2 out=$3
command -v codex >/dev/null || { echo "codex CLI not found" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq not found" >&2; exit 1; }
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
set -- exec "$(cat "$prompt")" --skip-git-repo-check --ephemeral --ignore-user-config --ignore-rules -s read-only --json
[ "$model" = "-" ] || set -- "$@" -m "$model"
if ! ( cd "$tmp" && env -u OPENAI_API_KEY -u OPENAI_BASE_URL codex "$@" </dev/null >"$tmp/events.jsonl" 2>"$tmp/err.txt" ); then
  tail -c 600 "$tmp/err.txt" >&2
  exit 1
fi
jq -e -s 'any(.[]; .type == "turn.completed")' "$tmp/events.jsonl" >/dev/null || { echo "codex: no completed turn" >&2; exit 1; }
jq -r -s '[.[] | select(.item.type? == "agent_message") | .item.text] | last // empty' "$tmp/events.jsonl" >"$out"
[ -s "$out" ] || { echo "codex: empty reply" >&2; exit 1; }
