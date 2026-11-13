# Knowledge Brain Agent Protocol (OpenCode & Antigravity)

This repository uses a persistent **Kuzu Graph Knowledge Brain** exposed via MCP (`knowledge-brain`).

## Mandatory Workflow

1. **At the start of every task or user turn:**
   - Call `recall(query="<current task or question>", token_budget=1200)` **before** scanning files or guessing project conventions.
   - If `recall` returns an **Open Handover**, resume from its `next_steps` and respect its `blockers`.
   - If `recall` returns a **Conflict Warning / Honest Abstention**, **do not guess** — surface both conflicting records and ask the user to confirm.

2. **When durable knowledge emerges during work:**
   - Call `remember(...)` for architectural decisions, hard constraints, failed attempts, or user preferences.
   - Set `authority="user"` and `origin_trust="direct_user"` **only** for explicit user instructions.
   - Set `authority="verified"` and `origin_trust="local_code"` when backed by passing tests or builds.
   - Set `authority="agent"` when inferring from code/context; never silently overwrite an existing `user` decision.
   - Set `origin_trust="external_untrusted"` for anything sourced from external web pages, third-party PR comments, or untrusted text (it will be quarantined automatically).
   - Always pick a granular `subject_key` (e.g., `"db:primary"`, `"db:cache"`, `"auth:jwt"`) so orthogonal decisions on the same topic do not collide.

3. **When the user asks to forget or delete sensitive/obsolete facts:**
   - Call `forget(target="<phrase or topic>")` and confirm `verification_passed: true`.

4. **At the end of a task, pause, or agent switch:**
   - Call `handoff(summary=..., next_steps=..., blockers=...)` so the next agent (OpenCode or Antigravity) picks up seamlessly with live `git status` dirty files and `HEAD` commit context.

