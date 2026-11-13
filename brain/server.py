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
    """MANDATORY ENTRYPOINT: Call recall FIRST on every task, question, or agent turn.

    Use this BEFORE scanning files, running shell commands, or guessing project conventions.
    Specifically triggers on questions about: project status, tech stack, architecture,
    requirements, past decisions, constraints, task history, handovers, or what was done.
    Retrieves compact, token-budgeted project context via hybrid semantic + BM25 search.
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
    """MANDATORY PERSISTENCE: Store durable decisions, constraints, failed attempts, or tech choices.

    Call this immediately whenever:
    - A tech stack, library, or framework is chosen or changed (kind='decision')
    - A requirement, validation rule, or security policy is introduced (kind='constraint')
    - A bug, dependency conflict, or failed approach is discovered (kind='failed_attempt')
    - A coding style or formatting rule is requested (kind='preference')
    Enforces the authority matrix (user > verified > agent), taint quarantine for
    external_untrusted sources, deduplication, and branch-aware supersession in Kuzu.
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
    """MANDATORY CHECKPOINT: Call at the end of any task, pause, milestone, or agent switch.

    Automatically enriches the checkpoint with live Git HEAD commit and uncommitted dirty files.
    Ensures the next session or agent resumes seamlessly with exact state and next steps.
    """
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
    """MANDATORY PRIVACY/CLEANUP: Redact obsolete memories, sensitive secrets, or rejected approaches.

    Performs cascading redaction across Memory, Source provenance, and Handover tables
    with mathematical 0-leak verification. Call whenever the user asks to remove, forget,
    or delete past information.
    """
    return get_service().forget(target=target, workspace_path=workspace_path)


def main() -> None:
    """Run the Knowledge Brain MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()

