---
name: handoff
description: Write .claude/handoff.md so a fresh session can resume this work without the chat history. Use for /handoff, before /clear, at the end of a session, or when context is filling up.
disable-model-invocation: true
---

# Handoff

Overwrite `.claude/handoff.md` (git-ignored) with the template below. A reader with zero context must be able to continue from it alone.

1. Collect facts by running them, not from memory: `git status --short`, `git log --oneline -5`, `git branch --show-current`. If the session touched the pipeline, rerun the last pipeline command and note its result.
2. Fill in the template. Keep it under 60 lines. Use file paths and commands, not prose about them. Record only what the repo can't tell the reader (decisions, dead ends, the reasons behind them, what the user asked for).
3. Reply with the path and the first next step, in one line each.

```markdown
# Handoff <YYYY-MM-DD HH:MM>

## Goal
<the user's goal and the problem behind it, in their terms>

## State
- branch <name>, last commit <sha subject>, uncommitted: <none | files>
- last check: <command and result | none>
- running/background: <none | what, where its output goes>

## Done this session
- <outcome, with the file or command that proves it>

## Next
1. <first concrete action: a command or file to edit>
2. ...

## Waiting on the user
- <decision or action only the user can take, or "none">

## Learned (don't re-discover)
- <gotcha, dead end, or fact with its evidence>

## Key files
- <path>: <why it matters now>
```
