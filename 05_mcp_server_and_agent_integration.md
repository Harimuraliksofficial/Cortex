# Component 5 — MCP Server and Agent Integration

## Purpose

The MCP Server is the interoperability layer.

It exposes Knowledge Brain functionality to different AI agents and IDEs without requiring each agent to understand Kuzu or the internal Memory Manager.

Conceptually:

```text
OpenCode -----------+
                    |
                    | MCP
                    v
              Knowledge Brain
                    ^
                    | MCP
                    |
Antigravity --------+
```

Both agents communicate with the same persistent backend.

---

# Recommended MCP tools

## 1. retrieve_memory

Purpose:

Retrieve relevant context for a task.

Example input:

```text
project_id
query
token_budget
```

Example use:

```text
What do I need to know before working on authentication?
```

---

## 2. propose_memory_update

Purpose:

Allow an agent to propose a structured memory change.

Example operations:

- ADD
- UPDATE
- SUPERSEDE
- DELETE
- NO_CHANGE

The MCP tool should not blindly trust the proposal.

It sends it to the Memory Manager for validation.

---

## 3. create_handover

Purpose:

Create a useful checkpoint when an agent stops.

Information can include:

- completed work;
- pending work;
- blockers;
- relevant files;
- next action.

The data becomes connected to the project and timeline.

---

## 4. explain_memory

Purpose:

Answer:

- Where did this fact come from?
- Why is this current?
- What replaced the old fact?

This exposes provenance without always putting it into normal retrieval context.

---

## 5. forget_memory

Purpose:

Process explicit deletion requests.

It should invoke the Memory Manager's deletion workflow rather than directly deleting one arbitrary graph node.

---

# Important MCP design principle

The MCP server should be thin.

Bad architecture:

```text
MCP tool
  -> contains all memory logic
  -> contains database queries
```

Better architecture:

```text
MCP Tool
   |
   v
Service / Memory Manager
   |
   +--> Retrieval Engine
   |
   +--> Database Access Layer
```

This keeps the system usable even outside MCP.

---

# OpenCode integration

For the first prototype:

1. Run Knowledge Brain as an independent MCP server.
2. Configure OpenCode to connect to it.
3. Expose the memory tools.
4. Give the agent instructions about when to use them.

Do not modify OpenCode source code initially.

The first integration test should be:

```text
Agent starts
  -> retrieve_memory

Agent performs work
  -> propose_memory_update

Restart
  -> retrieve_memory

Same information is available
```

---

# Second-agent integration

Connect Antigravity or another MCP-compatible agent to the same server/database.

Test:

```text
OpenCode:
  works on task
  stores handover

Antigravity:
  retrieves handover
  continues task
```

This is one of the strongest demonstrations of the project.

---

# Agent behavior

The agent should not call memory tools constantly.

Recommended checkpoints:

- before significant work;
- after important decisions;
- after major project changes;
- at task completion;
- before handover;
- when user explicitly requests remembering or forgetting.

The system should support NO_CHANGE so the graph is not polluted.

---

# End-to-end first milestone

The minimum complete demonstration:

1. Start Knowledge Brain database.
2. Start MCP server.
3. Connect OpenCode.
4. Agent stores one project decision.
5. Restart everything.
6. Agent retrieves the decision.
7. Connect a second agent.
8. Second agent retrieves the same decision.

After this works, add:

- automatic LLM extraction;
- contradictions;
- deletion verification;
- token measurement;
- richer timeline visualization.
