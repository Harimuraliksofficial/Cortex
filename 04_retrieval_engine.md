# Component 4 — Retrieval Engine

## Purpose

The Retrieval Engine answers:

> What does this agent need to know right now?

Its job is not to return the entire Knowledge Brain.

Its job is to retrieve a small, relevant, trustworthy context package.

---

# Core flow

```text
Current task
      |
      v
Understand query/task
      |
      v
Identify relevant project/entities
      |
      v
Query graph
      |
      v
Traverse related knowledge
      |
      v
Filter stale/invalid/deleted knowledge
      |
      v
Rank relevance
      |
      v
Fit within token budget
      |
      v
Return compact context
```

---

# Example

Agent asks:

```text
Continue working on authentication.
```

The Retrieval Engine may return:

```text
Project: ContestPlatform

Authentication:
- JWT selected as current approach.
- Login UI completed.
- Backend JWT integration pending.

Relevant files:
- apps/api/auth/auth.go
- apps/web/login.tsx

Last verified:
commit abc123
```

It should not return unrelated database history, UI styling decisions, or every project file.

---

# Graph traversal

The graph makes targeted retrieval possible.

Starting from:

```text
Task: Authentication
```

The engine can traverse:

```text
Task
 -> Project
 -> Decisions
 -> Files
 -> Technologies
 -> Sources
```

Then select only relevant nodes.

---

# Freshness

Not every stored fact has the same stability.

Architecture decision:

```text
Use Go
```

may remain valid for months.

File fact:

```text
auth.go exists
```

may become invalid after one commit.

The Retrieval Engine should consider:

- last verified time;
- Git commit;
- branch;
- status;
- validity period.

For volatile information, it can tell the agent:

```text
This file information was verified at commit abc123.
Verify current state before editing.
```

---

# Token budget

The system must measure and limit retrieved context.

A retrieval request should have a budget such as:

```text
max_tokens: 1500
```

The engine ranks candidates and returns the most useful information first.

Possible scoring factors:

- direct relevance to task;
- graph distance;
- source authority;
- freshness;
- current/active status;
- confidence.

---

# Provenance

When useful, returned facts should include compact evidence information.

Example:

```text
Database: MongoDB
Authority: explicit_user
Status: active
```

The agent can later call an explanation tool if it needs deeper evidence.

Do not always send every provenance detail to the model because that wastes tokens.

---

# Honest uncertainty

If the graph contains conflicting information, the Retrieval Engine should not silently pick a random answer.

Possible response:

```text
Conflicting database information exists and no sufficiently authoritative current decision was found.
```

This supports the benchmark requirement for honest abstention.

---

# First milestone

Implement:

```text
retrieve_memory(project_id, query, token_budget)
```

Test it with:

- authentication query;
- database query;
- unrelated query.

Measure:

- retrieved records;
- estimated tokens;
- retrieval latency.

Compare this with a full-history baseline.
