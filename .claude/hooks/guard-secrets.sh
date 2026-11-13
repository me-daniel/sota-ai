#!/bin/sh
# PreToolUse(Bash): block commands that read/copy/send secret files at any path depth
# (.env and .env.*, *.pem, *.key, credential and service-account JSON). Exit 2 = deny.
# .env.example is allowed. Mentions in strings (configs, comments) are not blocked.
# Limit: a program that opens the file itself (python -c "open('.env')") is not caught;
# the Read deny rules in settings.json and .gitignore still apply there.
cmd=$(jq -r '.tool_input.command // empty' | sed 's/\.env\.example//g')
p='[^ |;&<>"'"'"']'
secret="($p*/)?(\.env(\.[A-Za-z0-9_-]+)?|$p*\.(pem|key)|$p*(credentials|service-account)$p*\.json)"
end='["'"'"']?( |$|[|;&>)])'
verbs='(cat|less|more|head|tail|grep|rg|awk|sed|source|\.|cp|mv|scp|rsync|curl|base64|xxd|strings|open|bat|wc|diff|sort|uniq|cut|tr|tee|zip|tar)'
if printf '%s' "$cmd" | grep -Eq "$verbs( +-[^ ]+)*( +[^ |;&]+)* +[\"']?$secret$end|< *[\"']?$secret$end"; then
  echo "Blocked: command reads a secret file. Use .env.example for key names." >&2
  exit 2
fi
exit 0
