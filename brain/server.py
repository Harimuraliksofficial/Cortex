import sys
import os
from typing import Optional
from fastmcp import FastMCP

from brain.memory_service import MemoryService
from brain.db import get_db

# Initialize FastMCP application
mcp = FastMCP(
    name="knowledge-brain",
    instructions="""
    Knowledge Brain is a persistent graph memory server for coding agents.
    It tracks architectural decisions, technical constraints, failed approaches, and task handovers.
    Guidelines:
    1. At the start of a task, call `recall(query="...")` to fetch active decisions, constraints, and open handovers.
    2. When making an architectural choice, adopting a technical constraint, or when an approach failed, call `remember(...)`.
    3. Before completing your session or when paused, call `handoff(...)` to checkpoint work for the next agent.
    4. If the user asks to forget or remove sensitive data, call `forget(...)`.
    """
)

@mcp.tool()
def recall(query: str = "", token_budget: int = 1200, repo_path: str = "") -> str:
    """
    Retrieve relevant architectural decisions, constraints, and open handovers
    for the current repository and branch, fitted within the token budget.
    Always pass repo_path with the current workspace path to scope to the right project.
    """
    db = get_db()
    service = MemoryService(db)
    try:
        target_path = repo_path.strip() or None
        res = service.recall(query=query, token_budget=token_budget, repo_path=target_path)
        metrics = res["metrics"]
        header = f"<!-- KnowledgeBrain: {metrics['retrieved_tokens']} tokens (saved {metrics['savings_pct']}% vs full history, {metrics['latency_ms']}ms) -->\n"
        return header + res["context"]
    finally:
        db.close()

@mcp.tool()
def remember(
    title: str,
    content: str,
    topic: str = "general",
    kind: str = "decision",
    subject_key: str = "",
    authority: str = "user",
    origin_trust: str = "direct_user",
    replaces_previous: bool = False,
    repo_path: str = ""
) -> str:
    """
    Record an architectural decision, constraint, preference, or failed attempt.
    If authority is 'agent' and contradicts an explicit 'user' decision, it is safely quarantined as proposed.
    Always pass repo_path with the current workspace path to scope to the right project.
    """
    db = get_db()
    service = MemoryService(db)
    try:
        target_path = repo_path.strip() or None
        res = service.remember(
            title=title,
            content=content,
            topic=topic,
            kind=kind,
            subject_key=subject_key,
            authority=authority,
            origin_trust=origin_trust,
            replaces_previous=replaces_previous,
            repo_path=target_path
        )
        if res.get("conflict_detected"):
            return f"⚠️ Warning: Proposed {kind} '{title}' contradicts an existing user decision. Saved as proposed for review."
        if res.get("superseded_id"):
            return f"✅ Recorded {kind} '{title}'. Successfully superseded previous decision ({res['superseded_id']})."
        return f"✅ Recorded {kind} '{title}' (ID: {res['memory_id']}). Status: {res['recorded_status']}."
    finally:
        db.close()

@mcp.tool()
def handoff(summary: str, next_steps: str, blockers: str = "", repo_path: str = "") -> str:
    """
    Create a task checkpoint for the next agent session.
    Automatically captures currently modified uncommitted files live from Git.
    Always pass repo_path with the current workspace path to scope to the right project.
    """
    db = get_db()
    service = MemoryService(db)
    try:
        target_path = repo_path.strip() or None
        res = service.handoff(summary=summary, next_steps=next_steps, blockers=blockers, repo_path=target_path)
        dirty = res.get("dirty_files_captured", [])
        files_str = f" Modified files captured: {', '.join(dirty)}." if dirty else ""
        return f"✅ Handover checkpoint created (ID: {res['handover_id']}) on branch '{res['branch']}'.{files_str}"
    finally:
        db.close()

@mcp.tool()
def forget(target: str) -> str:
    """
    Cascading verified deletion: scrubs all memories and handovers matching the target,
    and runs a verification scan to guarantee 0 data leaks.
    """
    db = get_db()
    service = MemoryService(db)
    try:
        res = service.forget(target=target)
        if not res.get("verification_passed"):
            return f"⚠️ Deletion executed, but verification found {res['leak_count']} remaining traces."
        return (
            f"✅ Verified deletion complete for '{res['target']}'. "
            f"Scrubbed {res['scrubbed_memories']} memories and {res['scrubbed_handovers']} handovers. "
            f"Verification scan: 0 leaks."
        )
    finally:
        db.close()

if __name__ == "__main__":
    mcp.run()
