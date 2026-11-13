#!/bin/sh
# PreToolUse(Bash): block commands that read/copy/send secret files (.env, .env.local, *.pem). Exit 2 = deny.
# .env.example is allowed. Mentions in strings (configs, comments) are not blocked.
cmd=$(jq -r '.tool_input.command // empty')
secret='(\.env(\.[a-z]*local|\.production)?|[^ ]*\.pem|[^ ]*credentials[^ ]*\.json)'
if printf '%s' "$cmd" | grep -Eq "(cat|less|more|head|tail|grep|rg|awk|sed|source|\.|cp|mv|scp|rsync|curl|base64|xxd|strings|open|bat)( +-[^ ]+)*( +[^ |;&]+)* +(\./)?$secret( |$|[|;&>])"; then
  echo "Blocked: command reads a secret file. Use .env.example for key names." >&2
  exit 2
fi
exit 0
