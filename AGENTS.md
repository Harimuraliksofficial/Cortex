# Agent Guidelines for Knowledge Brain Integration

This repository is integrated with **Knowledge Brain** via the Model Context Protocol (MCP).
Use these guidelines to keep project knowledge synchronized across sessions and agents.

## When to Call MCP Tools

### 1. At the Start of Any Task
Call `recall(query="...")` with the task keywords (e.g. `recall(query="authentication setup")`).
- Retrieves active architectural decisions and constraints.
- Shows any open handovers left by previous agents on this branch.
- Checks uncommitted dirty files on disk automatically.

### 2. When an Architectural Decision is Made or Modified
Call `remember(...)`:
- **DO NOT** call `remember` for every line of code or syntax edit.
- **DO** call `remember` when:
  - Choosing a database, framework, or core library.
  - Adopting a hard technical constraint (e.g. "API must remain stateless for edge workers").
  - An approach was tried and failed (set `kind="failed_attempt"` to prevent future agents from repeating the mistake).
  - Replacing a previous decision (set `replaces_previous=true`).

### 3. Before Completing a Task or Ending a Session
Call `handoff(...)`:
- `summary`: What you completed.
- `next_steps`: Concrete actions for the next agent.
- `blockers`: Any failing tests or missing credentials.
- *Note:* Modified files are automatically detected and attached from Git.

### 4. When Explicitly Asked to Forget
Call `forget(target="...")` if a user asks to remove sensitive tokens, passwords, or deprecated facts.
