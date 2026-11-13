"""FastMCP server exposing Knowledge Brain tools: recall, remember, handoff, forget."""

from __future__ import annotations

import atexit
from typing import Any

from fastmcp import FastMCP

from brain.memory_service import MemoryService

mcp = FastMCP("knowledge-brain")

_service: MemoryService | None = None


def get_service() -> MemoryService:
    """Lazily initialize and return the singleton MemoryService."""
    global _service
    if _service is None:
        _service = MemoryService()
    return _service


def set_service(service: MemoryService | None) -> None:
    """Override the singleton MemoryService (primarily for testing)."""
    global _service
    _service = service


@atexit.register
def _shutdown() -> None:
    if _service is not None:
        _service.close()


@mcp.tool()
def recall(
    query: str,
    token_budget: int = 1200,
    workspace_path: str | None = None,
    session_id: str = "",
) -> dict[str, Any]:
    """Retrieve compact, token-budgeted project context via hybrid semantic + BM25 search.

    Returns open handovers, active decisions/constraints, linked failed attempts,
    global preferences, and conflict warnings / honest abstentions when records contradict.
    """
    return get_service().recall(
        query=query,
        token_budget=token_budget,
        workspace_path=workspace_path,
        session_id=session_id,
    )


@mcp.tool()
def remember(
    kind: str,
    topic: str,
    subject_key: str,
    title: str,
    content: str,
    authority: str = "agent",
    origin_trust: str | None = None,
    scope: str | None = None,
    replaces_previous: bool = True,
    branch: str | None = None,
    valid_until: str | None = None,
    agent_name: str = "mcp-agent",
    session_id: str = "",
    workspace_path: str | None = None,
) -> dict[str, Any]:
    """Store a durable decision, constraint, failed_attempt, or preference in Kuzu.

    Enforces the authority matrix (user > verified > agent), taint quarantine for
    external_untrusted sources, deduplication, and branch-aware supersession.
    """
    return get_service().remember(
        kind=kind,
        topic=topic,
        subject_key=subject_key,
        title=title,
        content=content,
        authority=authority,
        origin_trust=origin_trust,
        scope=scope,
        replaces_previous=replaces_previous,
        branch=branch,
        valid_until=valid_until,
        agent_name=agent_name,
        session_id=session_id,
        workspace_path=workspace_path,
    )


@mcp.tool()
def handoff(
    summary: str,
    next_steps: str,
    blockers: str = "",
    agent_name: str = "antigravity",
    session_id: str = "",
    workspace_path: str | None = None,
) -> dict[str, Any]:
    """Create a cross-agent checkpoint enriched with live Git HEAD and dirty files."""
    return get_service().handoff(
        summary=summary,
        next_steps=next_steps,
        blockers=blockers,
        agent_name=agent_name,
        session_id=session_id,
        workspace_path=workspace_path,
    )


@mcp.tool()
def forget(
    target: str,
    workspace_path: str | None = None,
) -> dict[str, Any]:
    """Redact all memories, provenance sources, and handovers matching target, with 0-leak verification."""
    return get_service().forget(target=target, workspace_path=workspace_path)


def main() -> None:
    """Run the Knowledge Brain MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()

