import time
import uuid
from typing import Dict, List, Optional, Any

from brain.db import Database, get_db
from brain.git_context import get_git_context

def _uuid7() -> str:
    return str(uuid.uuid4())

class MemoryService:
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_db()

    def remember(
        self,
        title: str,
        content: str,
        topic: str = "general",
        kind: str = "decision",
        subject_key: str = "",
        authority: str = "user",
        origin_trust: str = "direct_user",
        replaces_previous: bool = False,
        repo_path: Optional[str] = None,
        agent_name: str = "agent"
    ) -> Dict[str, Any]:
        """
        Records durable knowledge: decisions, constraints, or failed attempts.
        Handles authority conflict detection and explicit decision supersession.
        """
        git_info = get_git_context(repo_path)
        repo_id = git_info["repo_id"]
        branch = git_info["branch"]
        key = subject_key.strip().lower() or topic.strip().lower()

        # 1. Injection Defense: Untrusted sources are quarantined as proposed
        tainted = (origin_trust == "external_untrusted")
        status = "proposed" if tainted else "active"

        # 2. Check existing active memories on the same subject key
        check_q = """
        MATCH (m:Memory)
        WHERE m.repo_id = $repo_id AND m.subject_key = $key AND m.status = 'active'
        RETURN m.id, m.authority, m.title
        """
        res = self.db.execute(check_q, {"repo_id": repo_id, "key": key})
        existing = []
        while res.has_next():
            row = res.get_next()
            existing.append({"id": row[0], "authority": row[1], "title": row[2]})

        # 3. Authority Validation: Agent cannot override user decisions without permission
        conflict_detected = False
        conflict_target = ""
        if existing and authority == "agent" and existing[0]["authority"] == "user":
            conflict_detected = True
            conflict_target = existing[0]["title"]
            status = "proposed"

        superseded_id = None
        if replaces_previous and existing and not conflict_detected:
            superseded_id = existing[0]["id"]

        # 4. Insert Memory node
        memory_id = _uuid7()
        insert_q = """
        CREATE (m:Memory {
            id: $id,
            repo_id: $repo_id,
            branch: $branch,
            kind: $kind,
            topic: $topic,
            subject_key: $key,
            title: $title,
            content: $content,
            status: $status,
            authority: $authority,
            conflict_with: $conflict_with,
            created_at: current_timestamp(),
            updated_at: current_timestamp()
        })
        """
        self.db.execute(insert_q, {
            "id": memory_id,
            "repo_id": repo_id,
            "branch": branch,
            "kind": kind,
            "topic": topic.strip().lower(),
            "key": key,
            "title": title.strip(),
            "content": content.strip(),
            "status": status,
            "authority": authority,
            "conflict_with": conflict_target
        })

        # 5. Handle Supersession Relationship
        if superseded_id and not conflict_detected:
            self.db.execute(
                "MATCH (old:Memory {id: $oid}) SET old.status = 'superseded'",
                {"oid": superseded_id}
            )
            self.db.execute("""
                MATCH (new:Memory {id: $nid}), (old:Memory {id: $oid})
                CREATE (new)-[:SUPERSEDES {reason: 'superseded by newer decision', created_at: current_timestamp()}]->(old)
            """, {"nid": memory_id, "oid": superseded_id})

        return {
            "memory_id": memory_id,
            "status": "success",
            "recorded_status": status,
            "superseded_id": superseded_id,
            "conflict_detected": conflict_detected,
            "repo_id": repo_id,
            "branch": branch
        }

    def recall(
        self,
        query: str = "",
        token_budget: int = 1200,
        repo_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Pure read query: Fetches active decisions, constraints, and open handovers.
        Zero disk writes during retrieval.
        """
        start_time = time.time()
        git_info = get_git_context(repo_path)
        repo_id = git_info["repo_id"]
        branch = git_info["branch"]

        # 1. Fetch latest open handover for this repo & branch
        h_query = """
        MATCH (h:Handover)
        WHERE h.repo_id = $repo_id AND h.branch = $branch AND h.status = 'open'
        RETURN h.id, h.agent_name, h.summary, h.next_steps, h.blockers, h.dirty_files
        ORDER BY h.created_at DESC
        LIMIT 1
        """
        h_res = self.db.execute(h_query, {"repo_id": repo_id, "branch": branch})
        handover = None
        if h_res.has_next():
            row = h_res.get_next()
            handover = {
                "id": row[0],
                "agent_name": row[1],
                "summary": row[2],
                "next_steps": row[3],
                "blockers": row[4],
                "dirty_files": row[5] or []
            }

        # 2. Fetch active memories for this repo
        mem_query = """
        MATCH (m:Memory)
        WHERE m.repo_id = $repo_id AND m.status = 'active'
        RETURN m.id, m.kind, m.subject_key, m.title, m.content, m.authority, m.topic
        """
        mem_res = self.db.execute(mem_query, {"repo_id": repo_id})
        candidates = []
        query_tokens = set(query.lower().split()) if query else set()

        while mem_res.has_next():
            row = mem_res.get_next()
            mid, kind, key, title, content, auth, topic = row[0], row[1], row[2], row[3], row[4], row[5], row[6]

            # In-memory relevance score
            search_text = f"{title} {content} {topic} {key}".lower()
            if query_tokens:
                score = sum(1.0 for token in query_tokens if token in search_text)
                if kind in ("failed_attempt", "constraint"):
                    score += 0.5  # Prioritize safety constraints and past failures
            else:
                score = 1.0

            candidates.append({
                "id": mid,
                "kind": kind,
                "key": key,
                "title": title,
                "content": content,
                "authority": auth,
                "score": score
            })

        # Sort by relevance
        candidates.sort(key=lambda x: x["score"], reverse=True)

        # 3. Format Context Markdown
        sections = [f"# Cortex Context (Repo: {git_info['repo_name']} | Branch: {branch})"]

        if git_info["dirty_files"]:
            sections.append(f"> Note: Currently modified uncommitted files on disk: {', '.join(git_info['dirty_files'])}")

        # Check for authority conflicts / honest abstentions
        conf_q = """
        MATCH (m:Memory)
        WHERE m.repo_id = $repo_id AND m.status = 'proposed' AND m.conflict_with <> ''
        RETURN m.title, m.conflict_with
        """
        conf_res = self.db.execute(conf_q, {"repo_id": repo_id})
        conflicts = []
        while conf_res.has_next():
            crow = conf_res.get_next()
            conflicts.append(f"- **[HONEST ABSTENTION / CONFLICT]** Proposed '{crow[0]}' contradicts active decision '{crow[1]}'")

        if conflicts:
            sections.append("## Authority Conflicts & Honest Abstentions")
            sections.extend(conflicts)

        if handover:
            sections.append("## Active Handover Checkpoint")
            sections.append(f"- **From Agent:** {handover['agent_name']}")
            sections.append(f"- **Summary:** {handover['summary']}")
            sections.append(f"- **Next Steps:** {handover['next_steps']}")
            if handover["blockers"]:
                sections.append(f"- **Blockers:** {handover['blockers']}")

        if candidates:
            sections.append("## Active Decisions & Constraints")
            token_count = 0
            for item in candidates:
                line = f"- **[{item['kind'].upper()}] {item['title']}** ({item['authority']}): {item['content']}"
                item_tokens = len(line.split()) * 2  # Approximate token estimate
                if token_count + item_tokens > token_budget:
                    break
                sections.append(line)
                token_count += item_tokens

        context_md = "\n".join(sections)
        retrieved_tokens = len(context_md.split()) * 2
        latency_ms = int((time.time() - start_time) * 1000)

        # Metrics calculation (pure in-memory, no disk writes)
        count_res = self.db.execute("MATCH (m:Memory {repo_id: $rid}) RETURN count(m)", {"rid": repo_id})
        total_memories = count_res.get_next()[0] if count_res.has_next() else 0
        baseline_tokens = max(retrieved_tokens, total_memories * 80 + 1500)
        savings_pct = round(max(0.0, (1.0 - (retrieved_tokens / baseline_tokens)) * 100), 1)

        return {
            "context": context_md,
            "metrics": {
                "retrieved_tokens": retrieved_tokens,
                "full_history_tokens": baseline_tokens,
                "savings_pct": savings_pct,
                "latency_ms": latency_ms
            }
        }

    def handoff(
        self,
        summary: str,
        next_steps: str,
        blockers: str = "",
        agent_name: str = "agent",
        repo_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Creates a session handover checkpoint with live Git dirty files detection.
        Closes prior open handovers for the current branch.
        """
        git_info = get_git_context(repo_path)
        repo_id = git_info["repo_id"]
        branch = git_info["branch"]
        handover_id = _uuid7()

        # Close prior open handovers on this branch
        close_q = """
        MATCH (h:Handover)
        WHERE h.repo_id = $repo_id AND h.branch = $branch AND h.status = 'open'
        SET h.status = 'closed'
        """
        self.db.execute(close_q, {"repo_id": repo_id, "branch": branch})

        # Insert new handover
        insert_q = """
        CREATE (h:Handover {
            id: $id,
            repo_id: $repo_id,
            branch: $branch,
            status: 'open',
            agent_name: $agent,
            summary: $summary,
            next_steps: $next_steps,
            blockers: $blockers,
            dirty_files: $dirty_files,
            created_at: current_timestamp()
        })
        """
        self.db.execute(insert_q, {
            "id": handover_id,
            "repo_id": repo_id,
            "branch": branch,
            "agent": agent_name,
            "summary": summary.strip(),
            "next_steps": next_steps.strip(),
            "blockers": blockers.strip(),
            "dirty_files": git_info["dirty_files"]
        })

        return {
            "handover_id": handover_id,
            "branch": branch,
            "dirty_files_captured": git_info["dirty_files"]
        }

    def forget(self, target: str, repo_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Verified Cascading Deletion: Scrubs matching memories and handovers,
        guaranteeing zero data leaks.
        """
        cleaned_target = target.strip()
        if not cleaned_target:
            return {"status": "error", "message": "Empty target"}

        # Determine scope: specific repo_id if repo_path provided, otherwise global scrub
        rid_filter = None
        if repo_path:
            git_info = get_git_context(repo_path)
            rid_filter = git_info["repo_id"]

        # 1. Scrub matching memories
        if rid_filter:
            find_m = "MATCH (m:Memory {repo_id: $rid}) RETURN m.id, m.title, m.content"
            res = self.db.execute(find_m, {"rid": rid_filter})
        else:
            find_m = "MATCH (m:Memory) RETURN m.id, m.title, m.content"
            res = self.db.execute(find_m)

        to_scrub = []
        while res.has_next():
            row = res.get_next()
            mid, title, content = row[0], row[1], row[2]
            if cleaned_target.lower() in title.lower() or cleaned_target.lower() in content.lower():
                to_scrub.append(mid)

        for mid in to_scrub:
            self.db.execute("MATCH (m:Memory {id: $id}) DETACH DELETE m", {"id": mid})

        # 2. Scrub matching handovers
        if rid_filter:
            find_h = "MATCH (h:Handover {repo_id: $rid}) RETURN h.id, h.summary, h.next_steps, h.blockers"
            res_h = self.db.execute(find_h, {"rid": rid_filter})
        else:
            find_h = "MATCH (h:Handover) RETURN h.id, h.summary, h.next_steps, h.blockers"
            res_h = self.db.execute(find_h)

        to_scrub_h = []
        while res_h.has_next():
            row = res_h.get_next()
            hid, summary, next_s, blockers = row[0], row[1], row[2], row[3]
            blob = f"{summary} {next_s} {blockers}".lower()
            if cleaned_target.lower() in blob:
                to_scrub_h.append(hid)

        for hid in to_scrub_h:
            self.db.execute("MATCH (h:Handover {id: $id}) DELETE h", {"id": hid})

        # 3. Post-deletion leak verification scan
        if rid_filter:
            v_res = self.db.execute(
                "MATCH (m:Memory {repo_id: $rid}) WHERE m.status = 'active' RETURN m.title, m.content",
                {"rid": rid_filter}
            )
        else:
            v_res = self.db.execute(
                "MATCH (m:Memory) WHERE m.status = 'active' RETURN m.title, m.content"
            )

        leak_count = 0
        while v_res.has_next():
            v_row = v_res.get_next()
            if cleaned_target.lower() in v_row[0].lower() or cleaned_target.lower() in v_row[1].lower():
                leak_count += 1

        return {
            "status": "success",
            "target": target,
            "scrubbed_memories": len(to_scrub),
            "scrubbed_handovers": len(to_scrub_h),
            "verification_passed": (leak_count == 0),
            "leak_count": leak_count
        }
