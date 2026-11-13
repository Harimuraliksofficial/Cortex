l̥# Knowledge Brain (`knowledge-brain`)

A persistent, Kuzu-backed MCP Knowledge Brain for multi-agent coding memory (OpenCode, Antigravity, Claude Code).

## Features

- **Kuzu Graph Database**: Native embedded property graph storing decisions, constraints, failed attempts, preferences, handovers, and provenance events.
- **FastMCP Protocol**: Exposes 4 standard tools:
  - `recall`: Token-budgeted hybrid search (384-dimensional MiniLM embeddings + native BM25 full-text search) with conflict detection / honest abstention.
  - `remember`: Authority matrix (`user` > `verified` > `agent`), taint quarantine for untrusted inputs, deduplication, and branch-aware supersession.
  - `handoff`: Cross-agent checkpoints capturing Git branch, HEAD commit, and dirty working tree files.
  - `forget`: Cascading 0-leak redaction across memories, provenance sources, and handovers.
- **99%+ Context Token Savings**: Drastically reduces agent context overhead compared to full transcript replaying.

## Installation & Setup

```bash
pip install -e .
```

Dependencies:
- `kuzu>=0.7.0`
- `fastmcp>=2.0.0`
- `sentence-transformers>=3.0.0`

## MCP Server Invocation

Start the stdio MCP server:

```bash
python -m brain.server
```

Or configure in your agent's `.mcp.json`:

```json
{
  "mcpServers": {
    "knowledge-brain": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "brain.server"]
    }
  }
}
```

