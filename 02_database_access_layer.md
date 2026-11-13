# Component 2 — Database Access Layer

## Purpose

The Database Access Layer sits directly above the Graph Database Foundation.

Its job is to hide database-specific details from the rest of the application.

Instead of allowing every part of the system to write arbitrary Kuzu/Cypher queries, this layer provides controlled functions such as:

```text
create_project()
get_project()
create_decision()
get_active_decision()
create_event()
link_source()
mark_superseded()
soft_delete_memory()
```

---

# Why this layer is important

Without this layer:

```text
MCP Tool
  -> writes Cypher

Memory Manager
  -> writes Cypher

Retrieval Engine
  -> writes Cypher
```

Database logic becomes scattered and difficult to maintain.

Instead:

```text
MCP Server
      |
Memory Manager
      |
Retrieval Engine
      |
      v
Database Access Layer
      |
      v
Graph Database
```

This layer is the controlled gateway to persistence.

---

# Main responsibilities

## 1. CRUD operations

Provide operations to create, read, update, and delete graph records.

Examples:

```text
create_project()
get_project_by_id()
create_task()
update_task_status()
create_decision()
get_decision_history()
```

---

## 2. Relationship management

Knowledge is valuable because entities are connected.

This layer should create controlled relationships such as:

```text
project_uses_technology()
project_has_task()
decision_supported_by_source()
decision_supersedes_previous()
file_related_to_decision()
```

---

## 3. Transactions

An update may require multiple operations.

For example:

PostgreSQL -> MongoDB may require:

1. Find active PostgreSQL decision.
2. Mark old decision as superseded.
3. Set valid_until.
4. Create MongoDB decision.
5. Create SUPERSEDES relationship.
6. Link the new decision to evidence.
7. Create a timeline event.

These operations should be treated as one logical transaction when possible.

The system should avoid ending in a state where:

- PostgreSQL is marked inactive,
- but MongoDB was never created.

---

## 4. Schema-safe input

The Database Access Layer should not accept arbitrary unvalidated graph queries from an LLM.

Higher layers should pass structured objects.

Example:

```text
{
  operation: "CREATE_DECISION",
  project_id: "contest-platform",
  value: "MongoDB",
  authority: "explicit_user"
}
```

The Database Access Layer converts approved data into database operations.

---

## 5. Query helpers

The layer should provide reusable queries.

Examples:

- get current project technologies;
- get active decisions;
- get decision history;
- get related files;
- get project timeline;
- get evidence for a fact.

---

# Suggested structure

```text
db/
├── connection
├── schema
├── project_repository
├── decision_repository
├── task_repository
├── event_repository
└── source_repository
```

Each repository should focus on one group of entities.

---

# What this component should NOT do

It should not decide:

- whether information is important;
- whether an LLM statement is trustworthy;
- whether a contradiction should override a fact;
- which memories fit the token budget.

Those are responsibilities of the Memory Manager and Retrieval Engine.

---

# First milestone

Write a small program that:

1. Creates a Project.
2. Creates a Decision.
3. Links the Decision to the Project.
4. Reads it back.
5. Updates it through a controlled operation.
6. Restarts and reads it again.

Once this works, higher-level logic can safely be added.
