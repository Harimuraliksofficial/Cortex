# Component 3 — Memory Manager

## Purpose

The Memory Manager is the core logic of Cortex.

It sits between agents/MCP tools and the database.

Its responsibility is to manage the lifecycle of knowledge.

The graph database stores information.

The Memory Manager decides how approved information should be represented and changed.

---

# Core flow

```text
Agent proposes memory operation
          |
          v
     Memory Manager
          |
          +--> validate
          +--> inspect existing knowledge
          +--> detect update/conflict
          +--> manage lifecycle
          +--> create provenance
          +--> create timeline event
          |
          v
 Database Access Layer
          |
          v
      Graph Database
```

---

# Supported memory operations

The first version should support:

## ADD

Create new knowledge.

Example:

```text
Project uses JWT.
```

---

## UPDATE

Modify an existing record where historical replacement is not required.

Example:

```text
Task status: in_progress -> completed
```

---

## SUPERSEDE

Replace a previous durable fact while preserving history.

Example:

```text
PostgreSQL -> MongoDB
```

The old fact becomes historical and the new one becomes active.

---

## DELETE / FORGET

Remove knowledge according to the deletion policy.

Deletion should not simply mean deleting one visible node if the same information exists elsewhere.

The Memory Manager should locate related representations and report deletion status.

---

## NO_CHANGE

Important operation.

The system must be able to say:

```text
Nothing durable should be stored.
```

This prevents memory pollution.

---

# Validation

The Memory Manager validates proposed operations.

Examples:

- Is the target project valid?
- Does the previous fact actually exist?
- Is the proposed operation structurally valid?
- Is the source available?
- Does the authority level allow this information to override existing information?

---

# Authority model

Suggested authority ordering:

1. explicit_user
2. user_confirmed
3. verified_tool_observation
4. confirmed_agent_action
5. agent_proposal
6. llm_inference

This is not necessarily absolute truth, but it prevents weak information from silently overriding stronger information.

Example:

A low-confidence LLM inference should not replace an explicit user decision without review or evidence.

---

# Update example

Existing:

```text
Project -> USES_DATABASE -> PostgreSQL
status: active
```

New user instruction:

```text
Use MongoDB instead.
```

The Memory Manager should:

1. Identify this as an explicit update.
2. Locate the active previous decision.
3. Mark PostgreSQL as superseded.
4. set its validity end.
5. Create MongoDB as active.
6. Connect the new decision to the old one.
7. Link source evidence.
8. Create a timeline event.

---

# Contradictions

A contradiction is not always an update.

For example:

Memory says:

```text
Database: MongoDB
```

An agent later says:

```text
The project uses PostgreSQL.
```

The Memory Manager should not automatically overwrite the graph.

It should inspect:

- source authority;
- evidence;
- timestamp;
- whether this is a different branch/environment;
- whether the statement is a proposal or observation.

If unresolved, the system should preserve uncertainty.

---

# Abstention

Cortex must be allowed to say:

```text
I don't know.
```

If evidence is insufficient or conflicting, returning no confident answer is preferable to inventing knowledge.

---

# Timeline integration

Every significant memory operation should create an Event.

Example:

```text
Event:
type: DECISION_SUPERSEDED
timestamp: ...
actor: OpenCode agent
affected: ContestPlatform
```

This supports historical inspection and agent handovers.

---

# What this component should NOT do

The Memory Manager should not expose itself directly as a protocol.

MCP is the external interface.

It also should not require every raw conversation to be permanently stored.

It operates on structured proposals and evidence references.

---

# First milestone

Implement one complete scenario:

1. Add PostgreSQL.
2. Retrieve active database.
3. Supersede PostgreSQL with MongoDB.
4. Retrieve current database -> MongoDB.
5. Retrieve history -> PostgreSQL then MongoDB.
6. Show the timeline event.
