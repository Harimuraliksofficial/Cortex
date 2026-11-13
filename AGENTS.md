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

3. **Backfill on knowledge gaps (MANDATORY):**
   - After `recall`, if the returned context is **missing or insufficient** for the current task (e.g., no tech stack, no architecture, no endpoint list, no file structure) and you had to **read files, run commands, or explore the codebase** to fill the gap:
     - You **MUST** call `remember(...)` to store the discovered facts back into the brain before responding.
     - Use `authority="agent"`, `origin_trust="local_code"` for facts derived from reading the codebase.
     - Use granular `subject_key` values (e.g., `"project:overview"`, `"project:endpoints"`, `"bug:xyz"`).
   - **Why**: This ensures the brain gets richer over time. Future recalls by any agent or model should not need to re-read the same files to answer the same questions.
   - **Common backfill targets**: project overview/architecture, tech stack, API endpoint maps, DB schema details, file structure, known bugs or gaps found during exploration.

4. **When the user asks to forget or delete sensitive/obsolete facts:**
   - Call `forget(target="<phrase or topic>")` and confirm `verification_passed: true`.

5. **At the end of a task, pause, or agent switch:**
   - Call `handoff(summary=..., next_steps=..., blockers=...)` so the next agent (OpenCode or Antigravity) picks up seamlessly with live `git status` dirty files and `HEAD` commit context.

