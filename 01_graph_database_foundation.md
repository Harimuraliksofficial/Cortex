# Component 1 — Graph Database Foundation

## Purpose

This is the lowest layer of the Knowledge Brain. Its responsibility is to persist structured knowledge so that it survives process restarts, agent restarts, session changes, and handovers between different AI tools.

The graph database is **not** responsible for deciding whether something should be remembered. It is also not responsible for talking directly to OpenCode or Antigravity. It is the durable storage foundation that higher layers use.

For this project, the database should represent knowledge as:

- **Nodes**: important entities or records.
- **Relationships**: connections between entities.
- **Properties**: metadata attached to nodes/relationships.

The main advantage is that information is stored as connected knowledge rather than as one large document.

---

# Core design principle

Do not put the entire conversation into a single graph node.

Instead, represent meaningful parts of the agent's world separately. For example:

```text
Project
  ├── USES ───────────────> Technology
  ├── HAS_FILE ───────────> File
  ├── HAS_TASK ───────────> Task
  └── HAS_DECISION ───────> Decision

Decision
  ├── SUPERSEDES ─────────> Previous Decision
  ├── SUPPORTED_BY ───────> Source
  └── CREATED_BY_EVENT ───> Event
```

This allows the rest of the system to answer questions such as:

- What technologies does this project use?
- Why was this decision made?
- What decision replaced the previous one?
- Which file is related to this decision?
- What changed over time?
- Which agent made or verified this information?

---

# Recommended initial entities

## 1. Workspace

A logical container for projects.

Example:

```text
Workspace: HackathonTeam
```

A global Knowledge Brain can contain multiple workspaces and projects while keeping them logically separated.

---

## 2. Project

Represents a software project or repository.

Suggested properties:

- `id`: unique primary identifier.
- `name`: human-readable project name.
- `repository_path`: optional local path or repository identifier.
- `created_at`: when the project was registered.
- `updated_at`: latest modification time.

Example:

```text
Project {
  id: "contest-platform",
  name: "Contest Platform"
}
```

---

## 3. Technology

Represents reusable technologies such as:

- Go
- MongoDB
- PostgreSQL
- React
- JWT
- Kuzu

Technologies should normally be reusable nodes rather than duplicated text.

Example:

```text
(Project)-[:USES]->(Technology)
```

---

## 4. Decision

A decision represents an intentional choice.

Examples:

- Use MongoDB instead of PostgreSQL.
- Use JWT authentication.
- Use Go for the backend.

Suggested properties:

- `id`
- `title`
- `description`
- `status`: active, superseded, deleted, proposed.
- `authority`
- `confidence`
- `created_at`
- `updated_at`
- `valid_from`
- `valid_until`

The system should preserve historical decisions rather than simply overwriting them.

---

## 5. File

Represents a project file that is relevant to stored knowledge.

Suggested properties:

- `id`
- `project_id` or relationship to Project
- `path`
- `git_commit`
- `branch`
- `last_verified`

File facts are more volatile than architectural decisions. They should therefore include version/freshness metadata.

---

## 6. Task

Represents work being performed by an agent.

Suggested properties:

- `id`
- `title`
- `description`
- `status`: pending, in_progress, completed, blocked.
- `created_at`
- `updated_at`

Tasks support handovers between agents.

---

## 7. Source

Represents evidence or provenance.

A source may be:

- a user message,
- an agent response,
- a verified tool result,
- a file observation,
- a Git commit,
- a document.

Important properties:

- `id`
- `source_type`
- `session_id`
- `agent_id`
- `reference`
- `created_at`

Do not necessarily store every full raw conversation directly in the graph. The Source can point to the raw evidence storage or contain a compact evidence representation.

---

## 8. Event

Events provide the timeline.

Examples:

- Decision created.
- Decision updated.
- File modified.
- Task completed.
- Handover created.
- Memory deleted.

Suggested properties:

- `id`
- `event_type`
- `timestamp`
- `actor`
- `summary`

Events can connect to everything they affected.

---

# Core relationships

Recommended initial relationships:

```text
Workspace -[:CONTAINS]-> Project

Project -[:USES]-> Technology
Project -[:HAS_FILE]-> File
Project -[:HAS_TASK]-> Task
Project -[:HAS_DECISION]-> Decision

Decision -[:SUPERSEDES]-> Decision
Decision -[:SUPPORTED_BY]-> Source

Agent -[:PERFORMED]-> Event
Event -[:AFFECTED]-> Project
Event -[:CHANGED]-> Decision
```

The exact schema can evolve, but the first version should remain understandable.

---

# Temporal knowledge

One of the strongest features of the project should be that knowledge has a lifecycle.

For example:

```text
Project uses PostgreSQL
valid_from: Session 1
valid_until: Session 6
status: superseded
```

Later:

```text
Project uses MongoDB
valid_from: Session 6
valid_until: null
status: active
```

This makes the Knowledge Brain capable of answering both:

- What is true now?
- What was believed or active previously?

---

# Kuzu implementation responsibility

If Kuzu is used, this component should:

1. Initialize/open the database.
2. Create node tables.
3. Create relationship tables.
4. Enforce stable identifiers.
5. Perform database transactions.
6. Provide persistence across restarts.

Higher layers should ideally not contain raw database logic everywhere. They should call a repository/data-access layer.

---

# What this component should NOT do

The Graph Database Foundation should not:

- decide whether a user statement is important;
- perform LLM reasoning;
- decide semantic relevance;
- communicate directly with OpenCode;
- expose MCP tools;
- blindly resolve contradictions.

It stores and queries structured knowledge. The intelligence belongs in higher layers.

---

# First milestone

The first working milestone should demonstrate:

1. Create a database.
2. Create one Project.
3. Create PostgreSQL and MongoDB technology/decision records.
4. Create relationships.
5. Restart the application.
6. Query the database successfully.

Only after persistence works should the next layer be built.
