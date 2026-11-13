# MCP Server to Graph Database Interaction Architecture

> [!NOTE]
> This document details exactly how the **MCP Server** mediates between AI agents (OpenCode, Antigravity) and the **Kuzu Graph Database**, including the live Git context reader, conflict gate, cascading forget pipeline, and benchmark metrics.

---

## 1. Interaction Pipeline

The MCP server is a **stateless, thin translation layer**. It does not perform heavy AI reasoning itself; instead, it contextualizes calls with Git, validates inputs, and executes atomic Cypher transactions against Kuzu.

```text
┌────────────────────────────────────────────────────────┐
│             Agent (OpenCode / Antigravity)             │
└───────────────────────────┬────────────────────────────┘
                            │ JSON-RPC (MCP Tool Call)
                            ▼
┌────────────────────────────────────────────────────────┐
│                   MCP Server Router                    │
│      tools: [recall, remember, handoff, forget]        │
└───────────────┬────────────────────────────┬───────────┘
                │                            │
                ▼                            ▼
   ┌──────────────────────────┐  ┌───────────────────────┐
   │    Local Git Context     │  │ Ingestion & Conflict  │
   │    (read-only on disk)   │  │         Gate          │
   │                          │  │                       │
   │  • git rev-parse (repo)  │  │ • Deduplication hash  │
   │  • git branch (current)  │  │ • Authority check     │
   │  • git status (dirty)    │  │ • Taint / injection   │
   └────────────┬─────────────┘  └───────────┬───────────┘
                │                            │
                └──────────────┬─────────────┘
                               │ Structured Cypher Queries
                               ▼
┌────────────────────────────────────────────────────────┐
│             Kuzu Graph Database Engine                 │
│         (~/.knowledge-brain/brain.kuzu)                │
└────────────────────────────────────────────────────────┘
```

---

## 2. The 4 Core MCP Tools and Their DB Actions

### Tool 1: `recall` (Context Retrieval)
Called when an agent starts a task or needs context.

#### Agent Input:
```json
{
  "query": "authentication setup and database choice",
  "token_budget": 1200
}
```

#### MCP Server Execution Steps:
1. **Live Git Detection**: Executes `git rev-parse --show-toplevel` and `git branch --show-current` in the workspace to get `repo_id` and `branch`.
2. **Step 1 — Open Handovers**:
   ```cypher
   MATCH (h:Handover)-[:FOR_PROJECT]->(p:Project {id: $repo_id})
   WHERE h.status IN ['open', 'claimed'] AND (h.branch = $branch OR h.branch = '*')
   RETURN h ORDER BY h.created_at DESC LIMIT 1;
   ```
3. **Step 2 — Hybrid Semantic & Full-Text Search (Entry Node Matching)**:
   Instead of fragile exact string matching, Kuzu finds entry nodes using **Hybrid Search**:
   - **Vector Semantic Search**: Compares query embedding against `Memory.embedding` using cosine similarity (`array_cosine_similarity(m.embedding, $query_vec) > 0.70`). Matches conceptual synonyms like `"login"` -> `"JWT authentication"`.
   - **Full-Text BM25 Search**: Matches terms and stems using Kuzu's native `QUERY_FTS_INDEX('Memory', 'memory_fts', $query)`.
   
   Filters applied:
   - `status = 'active'`
   - `valid_until IS NULL OR valid_until > current_timestamp()`
   - Scope is `global` OR (`repo_id = $repo_id` AND `branch IN [$branch, '*', '__default__']`)
   - Excludes any memory superseded on this branch:
     `NOT EXISTS { MATCH (m)<-[:SUPERSEDES {branch: $branch}]-() }`
4. **Step 3 — 1-Hop Graph Traversal**:
   Follows `[:ABOUT]` to fetch linked `constraint`s or `failed_attempt`s.
5. **Step 4 — Contradiction / Abstention Check**:
   If conflicting decisions exist without resolution (`[:CONFLICTS_WITH]`), return an honest abstention:
   `"Conflicting records found for topic X: [A] vs [B]. User confirmation required."`
6. **Step 5 — Measure Metrics & Record**:
   Measures retrieval time, calculates `retrieved_tokens` vs `full_history_tokens`, and logs a `SessionMetric` node.
7. **Response to Agent**: Returns compact markdown formatted to fit within the `token_budget`.

---

### Tool 2: `remember` (Durable Knowledge Capture)
Called when an agent identifies a critical decision, constraint, or preference.

#### Agent Input:
```json
{
  "kind": "decision",
  "topic": "database",
  "subject_key": "db:primary",
  "title": "Use MongoDB for contest data",
  "content": "Contest schemas change weekly; MongoDB document model avoids migrations.",
  "authority": "user",
  "origin_trust": "direct_user",
  "replaces_previous": true
}
```

#### MCP Server Execution Steps:
1. **Security & Taint Gate**:
   - If `origin_trust == "external_untrusted"`, force `tainted = true` and `status = "proposed"`. It cannot overwrite active user decisions (planted memory defense).
2. **Duplicate Check**:
   - Computes `content_hash = SHA256(scope + branch + kind + subject_key + title)`. If already active, return existing ID with `NO_CHANGE`.
3. **Conflict & Supersession Evaluation**:
   - Query existing active memories with the same `(repo_id, topic, subject_key)`.
   - **If existing memory has `authority = 'user'` and new memory has `authority = 'agent'`:**
     Reject direct override. Create the new node as `status = "proposed"` and link `(new)-[:CONFLICTS_WITH {conflict_type: "authority_mismatch"}]->(existing)`.
   - **If replacing an existing decision (Authority OK):**
     Execute in a single transaction:
     ```cypher
     MATCH (old:Memory {id: $old_id})
     SET old.status = 'superseded'
     CREATE (new:Memory { ... })
     CREATE (new)-[:SUPERSEDES {branch: $branch, reason: $reason, created_at: timestamp()}]->(old)
     CREATE (new)-[:ABOUT {relevance: 1.0}]->(t:Topic {id: $topic_id})
     CREATE (e:Event {id: $event_id, event_type: 'SUPERSEDED', actor: $agent_name, summary: $summary})
     CREATE (e)-[:AFFECTED]->(new);
     ```

---

### Tool 3: `handoff` (Agent-to-Agent Checkpoint)
Called when an agent finishes its turn, pauses, or prepares a handover.

#### Agent Input:
```json
{
  "summary": "Completed auth middleware; tested invalid token rejection.",
  "next_steps": "Wire up refresh token endpoint in auth.go.",
  "blockers": "Need redis test container up on port 6379."
}
```

#### MCP Server Execution Steps:
1. **Live State Enrichment**: Server runs `git status --short` to capture modified files automatically into `dirty_files STRING[]`.
2. **Git Commit Hash**: Runs `git rev-parse HEAD` to capture `base_commit`.
3. **Transaction**:
   ```cypher
   CREATE (h:Handover {
       id: $handover_id,
       branch: $branch,
       status: 'open',
       agent_name: $agent_name,
       summary: $summary,
       next_steps: $next_steps,
       blockers: $blockers,
       base_commit: $base_commit,
       dirty_files: $dirty_files,
       created_at: timestamp(),
       updated_at: timestamp()
   })
   WITH h
   MATCH (p:Project {id: $repo_id})
   CREATE (h)-[:FOR_PROJECT]->(p)
   CREATE (e:Event {id: $event_id, event_type: 'HANDOVER_CREATED', actor: $agent_name, summary: $summary})
   CREATE (e)-[:AFFECTED]->(h);
   ```

---

### Tool 4: `forget` (Cascading Verified Forget)
Solves the `< 1.5%` deletion benchmark trap by verifying that no trace leaks back into future recall calls.

#### Agent Input:
```json
{
  "target": "JWT secret configuration"
}
```

#### MCP Server Execution Steps:
1. **Step 1 — Deep Cascade Match**:
   Find all nodes containing references to the target:
   - `Memory` nodes (`title`, `content`)
   - `Source` nodes (`excerpt`)
   - `Handover` nodes (`summary`, `next_steps`, `blockers`)
2. **Step 2 — Atomic Redaction / Tombstoning**:
   ```cypher
   // Soft delete memory with tombstone
   MATCH (m:Memory) WHERE m.title CONTAINS $target OR m.content CONTAINS $target
   SET m.status = 'deleted',
       m.title = '[REDACTED]',
       m.content = '[REDACTED_BY_USER_REQUEST]',
       m.deleted_at = timestamp(),
       m.deleted_reason = 'explicit_forget';

   // Redact provenance quotes
   MATCH (s:Source) WHERE s.excerpt CONTAINS $target
   SET s.excerpt = '[REDACTED_PROVENANCE]';

   // Redact handovers
   MATCH (h:Handover) WHERE h.summary CONTAINS $target OR h.next_steps CONTAINS $target
   SET h.summary = replace(h.summary, $target, '[REDACTED]'),
       h.next_steps = replace(h.next_steps, $target, '[REDACTED]');
   ```
3. **Step 3 — Post-Deletion Verification**:
   The MCP server executes an internal search for `$target`.
   If 0 active results return, `verification_passed = true`.
4. **Response**:
   ```json
   {
     "status": "success",
     "scrubbed_memories": 2,
     "scrubbed_sources": 1,
     "scrubbed_handovers": 1,
     "verification_passed": true
   }
   ```
