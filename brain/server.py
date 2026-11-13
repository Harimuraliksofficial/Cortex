"""FastMCP server exposing Knowledge Brain tools: recall, remember, handoff, forget."""

from __future__ import annotations

import atexit
from typing import Any

from fastmcp import FastMCP

from brain.activity_logger import log_activity
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
    res = get_service().recall(
        query=query,
        token_budget=token_budget,
        workspace_path=workspace_path,
        session_id=session_id,
    )
    status_label = "abstained" if res.get("abstained") else "success"
    log_activity(
        tool="recall",
        client=session_id or "antigravity",
        operation=f"Context query: '{query[:45]}...'",
        status=status_label,
        workspace=str(workspace_path or "current"),
        branch=res.get("branch", "main"),
        project_id=res.get("project_id", "default"),
        details={
            "retrieved_tokens": res.get("retrieved_tokens", 0),
            "savings_pct": res.get("savings_pct", 0),
            "latency_ms": res.get("latency_ms", 0),
            "memories_returned": res.get("memories_returned", 0),
            "abstained": res.get("abstained", False),
            "has_handover": bool(res.get("handover")),
        },
    )
    return res


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
    res = get_service().remember(
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
    log_activity(
        tool="remember",
        client=agent_name or "antigravity",
        operation=f"Stored {kind}: '{title[:45]}'",
        status=res.get("status", "recorded"),
        workspace=str(workspace_path or "current"),
        branch=res.get("branch", branch or "main"),
        project_id=res.get("project_id", "default"),
        details={
            "memory_id": res.get("memory_id"),
            "subject_key": subject_key,
            "kind": kind,
            "authority": authority,
            "tainted": res.get("tainted", False),
            "superseded_id": res.get("superseded_id"),
            "conflict_type": res.get("conflict_type"),
        },
    )
    return res


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
    res = get_service().handoff(
        summary=summary,
        next_steps=next_steps,
        blockers=blockers,
        agent_name=agent_name,
        session_id=session_id,
        workspace_path=workspace_path,
    )
    log_activity(
        tool="handoff",
        client=agent_name or "antigravity",
        operation=f"Created checkpoint: '{summary[:45]}...'",
        status=res.get("status", "handover_ready"),
        workspace=str(workspace_path or "current"),
        branch=res.get("branch", "main"),
        project_id=res.get("project_id", "default"),
        details={
            "handover_id": res.get("handover_id"),
            "dirty_files": res.get("dirty_files", []),
            "dirty_count": len(res.get("dirty_files", [])),
            "base_commit": res.get("base_commit"),
            "blockers": blockers,
        },
    )
    return res


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
    res = get_service().forget(target=target, workspace_path=workspace_path)
    log_activity(
        tool="forget",
        client="user",
        operation=f"Redacted target: '{target[:40]}'",
        status="success" if res.get("verification_passed") else "failed",
        workspace=str(workspace_path or "current"),
        details={
            "scrubbed_memories": res.get("scrubbed_memories", 0),
            "scrubbed_sources": res.get("scrubbed_sources", 0),
            "scrubbed_handovers": res.get("scrubbed_handovers", 0),
            "verification_passed": res.get("verification_passed", False),
        },
    )
    return res


def main() -> None:
    """Run the Knowledge Brain MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()

