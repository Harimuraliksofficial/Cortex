# Cortex: Persistent Graph Memory for Coding Agents

**Cortex (Knowledge Brain)** is a high-performance Model Context Protocol (MCP) server that provides AI coding agents with **persistent, branch-aware, and mutable memory** powered by an embedded graph database ([KùzuDB](https://kuzudb.com)).

Unlike traditional vector databases that suffer from outdated context, conflicting documents, and context bloat, Cortex tracks **active architectural decisions, explicit supersession lineages, negative knowledge (failed attempts), and task handovers**.

---

## ⚡ Core Capabilities

1. **Decision Supersession**: When a tool or framework is replaced (e.g. SQLite → SQLAlchemy), Cortex updates the old decision to `superseded` and creates an explicit `[:SUPERSEDES]` graph edge. Agents never hallucinate obsolete architectures.
2. **Negative Knowledge Tracking**: Store failed engineering attempts as `kind="failed_attempt"` to prevent future agents from repeating loops of known mistakes.
3. **Live Git Handover Checkpoints**: `handoff()` captures project summaries, next steps, blockers, and automatically discovers uncommitted dirty files from Git status without manual tracking.
4. **Authority & Injection Defense**: Untrusted external memories (e.g. untrusted README injections) are quarantined as `proposed`. Agent overrides against explicit user decisions are flagged as honest abstentions.
5. **Zero Disk Locks on Reads**: `recall()` is a 100% pure read operation (<30ms latency), allowing multiple concurrent tools, subagents, and terminals without file lock contention.

---

## 📁 Repository Structure

```
├── brain/
│   ├── __init__.py
│   ├── db.py               # Lean KùzuDB connection & schema (Memory, Handover, SUPERSEDES)
│   ├── git_context.py      # Batched live Git discovery (branch, commit, dirty files)
│   ├── memory_service.py   # Core logic: recall, remember, handoff, forget
│   └── server.py           # FastMCP stdio server exposing tools to agents
├── scripts/
│   ├── benchmark_30_sessions.py # Official 30-session evaluation benchmark
│   ├── test_git_timeline.py     # Live Git branch isolation demo
│   ├── brain_cli.py             # CLI bridge for running tools directly
│   └── audit_graph.py           # Database inspection & verification tool
├── .agents/
│   └── mcp_config.json     # Workspace-scoped Antigravity configuration
├── .mcp.json               # Standard VS Code / Cursor / Claude Desktop MCP config
├── opencode.json           # Native OpenCode MCP configuration
├── AGENTS.md               # Agent guidelines instructing models when to use Cortex
├── requirements.txt
└── pyproject.toml
```

---

## 🚀 Quickstart

### 1. Installation

```bash
git clone https://github.com/Harimuraliksofficial/Cortex.git
cd Cortex
pip install -r requirements.txt
```

### 2. Run the Benchmark

Verify that all 30 simulated sessions pass end-to-end:

```bash
python scripts/benchmark_30_sessions.py
```

### 3. Test Git Timeline Isolation

See how Cortex automatically isolates memories and captures uncommitted files across Git branches:

```bash
python scripts/test_git_timeline.py
```

---

## 🔌 Connecting to Coding Agents

### Antigravity (IDE & 2.0 Desktop)
Add Cortex to `~/.gemini/config/mcp_config.json` or `.agents/mcp_config.json`:

```json
{
  "mcpServers": {
    "knowledge-brain": {
      "command": "python",
      "args": ["-m", "brain.server"],
      "env": {
        "PYTHONPATH": ".",
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

### OpenCode
Add Cortex to `~/.config/opencode/opencode.jsonc` or `opencode.json`:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "knowledge-brain": {
      "type": "local",
      "command": ["python", "-m", "brain.server"],
      "environment": {
        "PYTHONPATH": ".",
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

### Claude Desktop / Cursor
Use the included `.mcp.json`.

---

## 🛠️ MCP Tool Reference

| Tool | Parameters | Description |
| :--- | :--- | :--- |
| `recall` | `query`, `token_budget`, `repo_path` | Retrieves active decisions, constraints, and open handovers fitted into the token budget. Pure read (<30ms). |
| `remember` | `title`, `content`, `topic`, `kind`, `subject_key`, `replaces_previous`, `repo_path` | Records durable knowledge (`decision`, `constraint`, `failed_attempt`). Supports decision supersession. |
| `handoff` | `summary`, `next_steps`, `blockers`, `repo_path` | Checkpoints current task state and attaches uncommitted dirty files from Git status. |
| `forget` | `target`, `repo_path` | Cascading verified deletion that scrubs matching memories with 0 leaks. |

---

## 📄 License
MIT License.
