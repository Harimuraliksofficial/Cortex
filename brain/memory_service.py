"""Core Knowledge Brain service: hybrid recall, authority/taint remember, handoff, verified forget."""

from __future__ import annotations

import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from brain.db import (
    BrainDatabase,
    VALID_AUTHORITIES,
    VALID_HANDOVER_STATUSES,
    VALID_KINDS,
    VALID_ORIGIN_TRUST,
    VALID_SCOPES,
    VALID_SOURCE_TYPES,
    canonicalize_topic_id,
    compute_content_hash,
    generate_uuidv7,
    truncate_excerpt,
)
from brain.embeddings import EMBEDDING_DIM, Embedder, get_embedder
from brain.git_context import GitContext, get_git_context

ZERO_VECTOR: list[float] = [0.0] * EMBEDDING_DIM


def estimate_tokens(text: str) -> int:
    """Estimate token count using ~4 chars/token heuristic."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def _sanitize_fts_query(query: str) -> str:
    """Keep alphanumeric/underscore tokens so Kuzu FTS parser never chokes on punctuation."""
    tokens = re.findall(r"[a-zA-Z0-9_]+", query or "")
    return " ".join(tokens)


def _parse_timestamp(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _cosine_similarity(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class MemoryService:
    """Stateless business-logic layer mediating MCP tools and Kuzu graph storage."""

    def __init__(
        self,
        db: BrainDatabase | None = None,
        db_path: str | Path | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self._owns_db = db is None
        self.db = db if db is not None else BrainDatabase(db_path=db_path)
        self._embedder = embedder

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = get_embedder()
        return self._embedder

    def close(self) -> None:
        if self._owns_db:
            self.db.close()

    def _embed(self, text: str) -> list[float]:
        return self.embedder.embed(text)

    # ------------------------------------------------------------------
    # Project & Topic helpers
    # ------------------------------------------------------------------

    def _ensure_project(self, ctx: GitContext) -> None:
        rows = self.db.query(
            "MATCH (p:Project {id: $id}) RETURN p.local_paths AS local_paths;",
            {"id": ctx.project_id},
        )
        if not rows:
            self.db.query(
                """
                CREATE (:Project {
                    id: $id,
                    name: $name,
                    git_remote_url: $remote,
                    root_commit_hash: $root_commit,
                    local_paths: $local_paths,
                    default_branch: $default_branch,
                    created_at: current_timestamp(),
                    updated_at: current_timestamp()
                });
                """,
                {
                    "id": ctx.project_id,
                    "name": ctx.project_name,
                    "remote": ctx.git_remote_url,
                    "root_commit": ctx.root_commit_hash,
                    "local_paths": [ctx.repo_root],
                    "default_branch": ctx.default_branch,
                },
            )
            return

        existing_paths = list(rows[0].get("local_paths") or [])
        if ctx.repo_root not in existing_paths:
            existing_paths.append(ctx.repo_root)
            self.db.query(
                """
                MATCH (p:Project {id: $id})
                SET p.local_paths = $local_paths, p.updated_at = current_timestamp();
                """,
                {"id": ctx.project_id, "local_paths": existing_paths},
            )

    def _ensure_topic(self, topic: str) -> str:
        topic_id = canonicalize_topic_id(topic)
        rows = self.db.query("MATCH (t:Topic {id: $id}) RETURN t.id AS id;", {"id": topic_id})
        if not rows:
            display_name = " ".join(part.capitalize() for part in topic_id.split("-"))
            self.db.query(
                """
                CREATE (:Topic {
                    id: $id,
                    display_name: $display_name,
                    aliases: $aliases,
                    created_at: current_timestamp()
                });
                """,
                {"id": topic_id, "display_name": display_name, "aliases": []},
            )
        return topic_id

    # ------------------------------------------------------------------
    # Tool 2: remember
    # ------------------------------------------------------------------

    def remember(
        self,
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
        valid_until: str | datetime | None = None,
        confidence: float | None = None,
        agent_name: str = "mcp-agent",
        session_id: str = "",
        source_type: str | None = None,
        source_excerpt: str | None = None,
        external_ref: str | None = None,
        workspace_path: str | Path | None = None,
    ) -> dict[str, Any]:
        """Persist durable knowledge with authority checks, taint quarantine, and branch-aware supersession."""
        kind_norm = kind.strip().lower()
        authority_norm = authority.strip().lower()
        scope_norm = (scope or ("global" if kind_norm == "preference" else "project")).strip().lower()

        if origin_trust is None:
            origin_trust_norm = "direct_user" if authority_norm == "user" else "local_code"
        else:
            origin_trust_norm = origin_trust.strip().lower()

        if source_type is None:
            source_type_norm = (
                "user_message" if origin_trust_norm == "direct_user" else "agent_summary"
            )
        else:
            source_type_norm = source_type.strip().lower()

        if kind_norm not in VALID_KINDS:
            raise ValueError(f"Invalid kind '{kind}'. Expected one of {sorted(VALID_KINDS)}")
        if scope_norm not in VALID_SCOPES:
            raise ValueError(f"Invalid scope '{scope_norm}'. Expected one of {sorted(VALID_SCOPES)}")
        if authority_norm not in VALID_AUTHORITIES:
            raise ValueError(
                f"Invalid authority '{authority_norm}'. Expected one of {sorted(VALID_AUTHORITIES)}"
            )
        if origin_trust_norm not in VALID_ORIGIN_TRUST:
            raise ValueError(
                f"Invalid origin_trust '{origin_trust_norm}'. Expected one of {sorted(VALID_ORIGIN_TRUST)}"
            )
        if source_type_norm not in VALID_SOURCE_TYPES:
            raise ValueError(
                f"Invalid source_type '{source_type_norm}'. Expected one of {sorted(VALID_SOURCE_TYPES)}"
            )

        ctx = get_git_context(workspace_path)
        if scope_norm == "project":
            self._ensure_project(ctx)
        topic_id = self._ensure_topic(topic)

        # Invariant 1: global scope MUST have branch="*" and NO IN_PROJECT edge.
        effective_branch = "*" if scope_norm == "global" else (branch or ctx.branch)
        subject_norm = subject_key.strip().lower()
        title_clean = title.strip()
        content_clean = content.strip()
        valid_until_dt = _parse_timestamp(valid_until)
        content_hash = compute_content_hash(
            scope=scope_norm,
            branch=effective_branch,
            kind=kind_norm,
            subject_key=subject_norm,
            title=title_clean,
        )

        if confidence is None:
            confidence_val = {"user": 0.98, "verified": 0.92, "agent": 0.75}[authority_norm]
        else:
            confidence_val = float(confidence)

        is_tainted = origin_trust_norm == "external_untrusted"
        embedding = self._embed(f"{topic_id} {subject_norm} {title_clean}. {content_clean}")
        excerpt = truncate_excerpt(source_excerpt if source_excerpt is not None else content_clean)

        # 1. Taint Quarantine Gate (never overwrites or supersedes active knowledge)
        if is_tainted:
            memory_id = self._write_memory_record(
                ctx=ctx,
                scope=scope_norm,
                branch=effective_branch,
                kind=kind_norm,
                subject_key=subject_norm,
                title=title_clean,
                content=content_clean,
                status="proposed",
                authority=authority_norm,
                confidence=min(confidence_val, 0.3),
                embedding=embedding,
                tainted=True,
                origin_trust=origin_trust_norm,
                valid_until=valid_until_dt,
                content_hash=content_hash,
                topic_id=topic_id,
                agent_name=agent_name,
                session_id=session_id,
                source_type=source_type_norm,
                excerpt=excerpt,
                external_ref=external_ref,
                event_type="CREATED",
                event_summary=f"Quarantined untrusted memory '{title_clean}'",
            )
            return {
                "status": "quarantined",
                "memory_id": memory_id,
                "memory_status": "proposed",
                "tainted": True,
                "branch": effective_branch,
                "project_id": ctx.project_id if scope_norm == "project" else None,
                "topic_id": topic_id,
                "content_hash": content_hash,
            }

        # 2. Idempotency / Duplicate Check
        dup_id = self._find_duplicate_active(
            scope=scope_norm,
            project_id=ctx.project_id,
            content_hash=content_hash,
        )
        if dup_id:
            return {
                "status": "no_change",
                "reason": "duplicate_content_hash",
                "memory_id": dup_id,
                "memory_status": "active",
                "tainted": False,
                "branch": effective_branch,
                "project_id": ctx.project_id if scope_norm == "project" else None,
                "topic_id": topic_id,
                "content_hash": content_hash,
            }

        # 3. Conflict & Authority Evaluation
        existing = self._find_active_by_subject(
            scope=scope_norm,
            project_id=ctx.project_id,
            branch=effective_branch,
            default_branch=ctx.default_branch,
            subject_key=subject_norm,
        )

        if not existing:
            memory_id = self._write_memory_record(
                ctx=ctx,
                scope=scope_norm,
                branch=effective_branch,
                kind=kind_norm,
                subject_key=subject_norm,
                title=title_clean,
                content=content_clean,
                status="active",
                authority=authority_norm,
                confidence=confidence_val,
                embedding=embedding,
                tainted=False,
                origin_trust=origin_trust_norm,
                valid_until=valid_until_dt,
                content_hash=content_hash,
                topic_id=topic_id,
                agent_name=agent_name,
                session_id=session_id,
                source_type=source_type_norm,
                excerpt=excerpt,
                external_ref=external_ref,
                event_type="CREATED",
                event_summary=f"Recorded {kind_norm} '{title_clean}'",
            )
            return {
                "status": "recorded",
                "memory_id": memory_id,
                "memory_status": "active",
                "tainted": False,
                "branch": effective_branch,
                "project_id": ctx.project_id if scope_norm == "project" else None,
                "topic_id": topic_id,
                "content_hash": content_hash,
            }

        # Prefer matching branch target, else fallback to first active record on subject_key
        target_old = next(
            (row for row in existing if row["branch"] == effective_branch),
            existing[0],
        )
        old_authority = target_old["authority"]

        # Authority Matrix enforcement:
        # - agent cannot override user or verified
        # - verified cannot override user
        authority_blocked = (
            (authority_norm == "agent" and old_authority in {"user", "verified"})
            or (authority_norm == "verified" and old_authority == "user")
        )

        if authority_blocked:
            memory_id = self._write_conflict_record(
                ctx=ctx,
                scope=scope_norm,
                branch=effective_branch,
                kind=kind_norm,
                subject_key=subject_norm,
                title=title_clean,
                content=content_clean,
                new_status="proposed",
                authority=authority_norm,
                confidence=confidence_val,
                embedding=embedding,
                origin_trust=origin_trust_norm,
                valid_until=valid_until_dt,
                content_hash=content_hash,
                topic_id=topic_id,
                agent_name=agent_name,
                session_id=session_id,
                source_type=source_type_norm,
                excerpt=excerpt,
                external_ref=external_ref,
                old_id=target_old["id"],
                conflict_type="authority_mismatch",
            )
            return {
                "status": "conflict_proposed",
                "memory_id": memory_id,
                "conflicting_with_id": target_old["id"],
                "conflict_type": "authority_mismatch",
                "memory_status": "proposed",
                "tainted": False,
                "branch": effective_branch,
                "project_id": ctx.project_id if scope_norm == "project" else None,
                "topic_id": topic_id,
                "content_hash": content_hash,
            }

        # Non-replacing contradictory write -> flag unresolved value_contradiction
        if not replaces_previous:
            new_status = "active" if authority_norm == "user" else "proposed"
            memory_id = self._write_conflict_record(
                ctx=ctx,
                scope=scope_norm,
                branch=effective_branch,
                kind=kind_norm,
                subject_key=subject_norm,
                title=title_clean,
                content=content_clean,
                new_status=new_status,
                authority=authority_norm,
                confidence=confidence_val,
                embedding=embedding,
                origin_trust=origin_trust_norm,
                valid_until=valid_until_dt,
                content_hash=content_hash,
                topic_id=topic_id,
                agent_name=agent_name,
                session_id=session_id,
                source_type=source_type_norm,
                excerpt=excerpt,
                external_ref=external_ref,
                old_id=target_old["id"],
                conflict_type="value_contradiction",
            )
            return {
                "status": "conflict_flagged",
                "memory_id": memory_id,
                "conflicting_with_id": target_old["id"],
                "conflict_type": "value_contradiction",
                "memory_status": new_status,
                "tainted": False,
                "branch": effective_branch,
                "project_id": ctx.project_id if scope_norm == "project" else None,
                "topic_id": topic_id,
                "content_hash": content_hash,
            }

        # Authority OK + replaces_previous=True -> Atomic Branch-Aware Supersession
        memory_id = self._write_supersession_record(
            ctx=ctx,
            scope=scope_norm,
            branch=effective_branch,
            kind=kind_norm,
            subject_key=subject_norm,
            title=title_clean,
            content=content_clean,
            authority=authority_norm,
            confidence=confidence_val,
            embedding=embedding,
            origin_trust=origin_trust_norm,
            valid_until=valid_until_dt,
            content_hash=content_hash,
            topic_id=topic_id,
            agent_name=agent_name,
            session_id=session_id,
            source_type=source_type_norm,
            excerpt=excerpt,
            external_ref=external_ref,
            old_row=target_old,
        )
        return {
            "status": "recorded",
            "memory_id": memory_id,
            "superseded_id": target_old["id"],
            "memory_status": "active",
            "tainted": False,
            "branch": effective_branch,
            "project_id": ctx.project_id if scope_norm == "project" else None,
            "topic_id": topic_id,
            "content_hash": content_hash,
        }

    def _find_duplicate_active(
        self,
        scope: str,
        project_id: str,
        content_hash: str,
    ) -> str | None:
        if scope == "global":
            rows = self.db.query(
                """
                MATCH (m:Memory)
                WHERE m.scope = 'global'
                  AND m.status = 'active'
                  AND m.content_hash = $content_hash
                RETURN m.id AS id LIMIT 1;
                """,
                {"content_hash": content_hash},
            )
        else:
            rows = self.db.query(
                """
                MATCH (m:Memory)-[:IN_PROJECT]->(p:Project {id: $project_id})
                WHERE m.status = 'active'
                  AND m.content_hash = $content_hash
                RETURN m.id AS id LIMIT 1;
                """,
                {"project_id": project_id, "content_hash": content_hash},
            )
        return rows[0]["id"] if rows else None

    def _find_active_by_subject(
        self,
        scope: str,
        project_id: str,
        branch: str,
        default_branch: str,
        subject_key: str,
    ) -> list[dict[str, Any]]:
        if scope == "global":
            return self.db.query(
                """
                MATCH (m:Memory)
                WHERE m.scope = 'global'
                  AND m.status = 'active'
                  AND m.tainted = false
                  AND m.subject_key = $subject_key
                  AND (m.valid_until IS NULL OR m.valid_until > current_timestamp())
                  AND NOT EXISTS { MATCH (m)<-[:SUPERSEDES {branch: '*'}]-() }
                RETURN m.id AS id, m.branch AS branch, m.authority AS authority, m.title AS title
                ORDER BY m.created_at DESC;
                """,
                {"subject_key": subject_key},
            )

        allowed_branches = list({branch, "*", default_branch})
        return self.db.query(
            """
            MATCH (m:Memory)-[:IN_PROJECT]->(p:Project {id: $project_id})
            WHERE m.status = 'active'
              AND m.tainted = false
              AND m.subject_key = $subject_key
              AND m.branch IN $branches
              AND (m.valid_until IS NULL OR m.valid_until > current_timestamp())
              AND NOT EXISTS { MATCH (m)<-[:SUPERSEDES {branch: $branch}]-() }
              AND NOT EXISTS { MATCH (m)<-[:SUPERSEDES {branch: '*'}]-() }
            RETURN m.id AS id, m.branch AS branch, m.authority AS authority, m.title AS title
            ORDER BY m.created_at DESC;
            """,
            {
                "project_id": project_id,
                "subject_key": subject_key,
                "branches": allowed_branches,
                "branch": branch,
            },
        )

    def _create_memory_and_links_in_tx(
        self,
        *,
        memory_id: str,
        ctx: GitContext,
        scope: str,
        branch: str,
        kind: str,
        subject_key: str,
        title: str,
        content: str,
        status: str,
        authority: str,
        confidence: float,
        embedding: list[float],
        tainted: bool,
        origin_trust: str,
        valid_until: datetime | None,
        content_hash: str,
        topic_id: str,
        agent_name: str,
        session_id: str,
        source_type: str,
        excerpt: str,
        external_ref: str | None,
    ) -> None:
        source_id = generate_uuidv7()
        self.db.query(
            """
            CREATE (:Memory {
                id: $id,
                scope: $scope,
                branch: $branch,
                kind: $kind,
                subject_key: $subject_key,
                title: $title,
                content: $content,
                status: $status,
                authority: $authority,
                confidence: $confidence,
                embedding: CAST($embedding AS FLOAT[384]),
                tainted: $tainted,
                origin_trust: $origin_trust,
                git_head_at_write: $git_head,
                valid_from: current_timestamp(),
                valid_until: $valid_until,
                deleted_at: NULL,
                deleted_reason: NULL,
                content_hash: $content_hash,
                created_at: current_timestamp(),
                updated_at: current_timestamp()
            });
            """,
            {
                "id": memory_id,
                "scope": scope,
                "branch": branch,
                "kind": kind,
                "subject_key": subject_key,
                "title": title,
                "content": content,
                "status": status,
                "authority": authority,
                "confidence": confidence,
                "embedding": embedding,
                "tainted": tainted,
                "origin_trust": origin_trust,
                "git_head": ctx.head_commit,
                "valid_until": valid_until,
                "content_hash": content_hash,
            },
        )
        if scope == "project":
            self.db.query(
                """
                MATCH (m:Memory {id: $memory_id}), (p:Project {id: $project_id})
                CREATE (m)-[:IN_PROJECT]->(p);
                """,
                {"memory_id": memory_id, "project_id": ctx.project_id},
            )
        self.db.query(
            """
            MATCH (m:Memory {id: $memory_id}), (t:Topic {id: $topic_id})
            CREATE (m)-[:ABOUT {relevance: 1.0}]->(t);
            """,
            {"memory_id": memory_id, "topic_id": topic_id},
        )
        self.db.query(
            """
            CREATE (:Source {
                id: $source_id,
                source_type: $source_type,
                origin_trust: $origin_trust,
                tainted: $tainted,
                agent_name: $agent_name,
                session_id: $session_id,
                excerpt: $excerpt,
                external_ref: $external_ref,
                created_at: current_timestamp()
            });
            """,
            {
                "source_id": source_id,
                "source_type": source_type,
                "origin_trust": origin_trust,
                "tainted": tainted,
                "agent_name": agent_name,
                "session_id": session_id,
                "excerpt": excerpt,
                "external_ref": external_ref,
            },
        )
        self.db.query(
            """
            MATCH (m:Memory {id: $memory_id}), (s:Source {id: $source_id})
            CREATE (m)-[:SUPPORTED_BY]->(s);
            """,
            {"memory_id": memory_id, "source_id": source_id},
        )

    def _write_memory_record(
        self,
        *,
        event_type: str,
        event_summary: str,
        **kwargs: Any,
    ) -> str:
        memory_id = generate_uuidv7()
        event_id = generate_uuidv7()
        self.db.query("BEGIN TRANSACTION;")
        try:
            self._create_memory_and_links_in_tx(memory_id=memory_id, **kwargs)
            self.db.query(
                """
                CREATE (:Event {
                    id: $event_id,
                    event_type: $event_type,
                    actor: $actor,
                    summary: $summary,
                    created_at: current_timestamp()
                });
                """,
                {
                    "event_id": event_id,
                    "event_type": event_type,
                    "actor": kwargs["agent_name"],
                    "summary": event_summary,
                },
            )
            self.db.query(
                """
                MATCH (e:Event {id: $event_id}), (m:Memory {id: $memory_id})
                CREATE (e)-[:AFFECTED]->(m);
                """,
                {"event_id": event_id, "memory_id": memory_id},
            )
            self.db.query("COMMIT;")
        except Exception:
            self.db.query("ROLLBACK;")
            raise
        return memory_id

    def _write_conflict_record(
        self,
        *,
        new_status: str,
        old_id: str,
        conflict_type: str,
        **kwargs: Any,
    ) -> str:
        memory_id = generate_uuidv7()
        event_id = generate_uuidv7()
        self.db.query("BEGIN TRANSACTION;")
        try:
            self._create_memory_and_links_in_tx(
                memory_id=memory_id,
                status=new_status,
                tainted=False,
                **kwargs,
            )
            self.db.query(
                """
                MATCH (n:Memory {id: $new_id}), (o:Memory {id: $old_id})
                CREATE (n)-[:CONFLICTS_WITH {
                    conflict_type: $conflict_type,
                    resolution_status: 'unresolved',
                    detected_at: current_timestamp()
                }]->(o);
                """,
                {
                    "new_id": memory_id,
                    "old_id": old_id,
                    "conflict_type": conflict_type,
                },
            )
            self.db.query(
                """
                CREATE (:Event {
                    id: $event_id,
                    event_type: 'CONFLICT_FLAGGED',
                    actor: $actor,
                    summary: $summary,
                    created_at: current_timestamp()
                });
                """,
                {
                    "event_id": event_id,
                    "actor": kwargs["agent_name"],
                    "summary": f"{conflict_type} between {memory_id} and {old_id}",
                },
            )
            self.db.query(
                """
                MATCH (e:Event {id: $event_id}), (m:Memory {id: $memory_id})
                CREATE (e)-[:AFFECTED]->(m);
                """,
                {"event_id": event_id, "memory_id": memory_id},
            )
            self.db.query("COMMIT;")
        except Exception:
            self.db.query("ROLLBACK;")
            raise
        return memory_id

    def _write_supersession_record(
        self,
        *,
        old_row: dict[str, Any],
        **kwargs: Any,
    ) -> str:
        memory_id = generate_uuidv7()
        event_id = generate_uuidv7()
        old_id = old_row["id"]
        same_branch = old_row["branch"] == kwargs["branch"]
        self.db.query("BEGIN TRANSACTION;")
        try:
            # Same-branch replacement flips old.status='superseded';
            # Cross-branch override keeps main/default active and marks edge {branch}.
            if same_branch:
                self.db.query(
                    """
                    MATCH (o:Memory {id: $old_id})
                    SET o.status = 'superseded', o.updated_at = current_timestamp();
                    """,
                    {"old_id": old_id},
                )
            self._create_memory_and_links_in_tx(
                memory_id=memory_id,
                status="active",
                tainted=False,
                **kwargs,
            )
            self.db.query(
                """
                MATCH (n:Memory {id: $new_id}), (o:Memory {id: $old_id})
                CREATE (n)-[:SUPERSEDES {
                    branch: $branch,
                    reason: $reason,
                    created_at: current_timestamp()
                }]->(o);
                """,
                {
                    "new_id": memory_id,
                    "old_id": old_id,
                    "branch": kwargs["branch"],
                    "reason": kwargs["content"][:200],
                },
            )
            self.db.query(
                """
                CREATE (:Event {
                    id: $event_id,
                    event_type: 'SUPERSEDED',
                    actor: $actor,
                    summary: $summary,
                    created_at: current_timestamp()
                });
                """,
                {
                    "event_id": event_id,
                    "actor": kwargs["agent_name"],
                    "summary": f"'{kwargs['title']}' superseded '{old_row['title']}' on branch '{kwargs['branch']}'",
                },
            )
            self.db.query(
                """
                MATCH (e:Event {id: $event_id}), (m:Memory {id: $memory_id})
                CREATE (e)-[:AFFECTED]->(m);
                """,
                {"event_id": event_id, "memory_id": memory_id},
            )
            self.db.query("COMMIT;")
        except Exception:
            self.db.query("ROLLBACK;")
            raise
        return memory_id

    # ------------------------------------------------------------------
    # Tool 1: recall
    # ------------------------------------------------------------------

    def recall(
        self,
        query: str,
        token_budget: int = 1200,
        workspace_path: str | Path | None = None,
        session_id: str = "",
        full_history_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Hybrid search + 1-hop traversal + conflict check + token-budget packing."""
        start_ns = time.perf_counter_ns()
        ctx = get_git_context(workspace_path)
        budget = max(120, int(token_budget))

        # Step 1: Latest open handover on current branch (or '*')
        handover = self._fetch_latest_handover(ctx.project_id, ctx.branch)

        # Step 2: Hybrid Search (Vector Cosine + BM25 FTS)
        candidates = self._hybrid_search(query=query, ctx=ctx, limit=15)

        # Step 3: 1-hop graph traversal over [:ABOUT] for constraints & failed_attempts
        linked_extras = self._fetch_linked_constraints_and_failures(
            candidate_ids=[c["id"] for c in candidates],
            ctx=ctx,
        )

        # Global preferences (always eligible as low-priority context)
        global_prefs = self._fetch_global_preferences(limit=5)

        # Step 4: Conflict / Honest Abstention Check across matched candidates
        all_matched_ids = list({c["id"] for c in candidates} | {e["id"] for e in linked_extras})
        conflicts = self._fetch_unresolved_conflicts(all_matched_ids)
        # Filter out value_contradiction nodes from uncontested decisions when abstaining
        conflicted_node_ids = {
            c["new_id"] for c in conflicts if c["conflict_type"] == "value_contradiction"
        } | {
            c["old_id"] for c in conflicts if c["conflict_type"] == "value_contradiction"
        }
        has_value_conflict = bool(conflicted_node_ids)

        decisions_and_constraints = [
            c
            for c in candidates
            if c["kind"] in {"decision", "constraint"} and c["id"] not in conflicted_node_ids
        ]
        # Append 1-hop constraints not already in candidates
        seen_ids = {c["id"] for c in decisions_and_constraints}
        for extra in linked_extras:
            if extra["kind"] == "constraint" and extra["id"] not in seen_ids and extra["id"] not in conflicted_node_ids:
                decisions_and_constraints.append(extra)
                seen_ids.add(extra["id"])

        failed_attempts = [c for c in candidates if c["kind"] == "failed_attempt"]
        seen_failures = {c["id"] for c in failed_attempts}
        for extra in linked_extras:
            if extra["kind"] == "failed_attempt" and extra["id"] not in seen_failures:
                failed_attempts.append(extra)
                seen_failures.add(extra["id"])

        # Step 5: Token-Budget Packing Algorithm (strict priority order)
        packed_md = self._pack_context(
            token_budget=budget,
            handover=handover,
            decisions=decisions_and_constraints,
            failures=failed_attempts,
            preferences=global_prefs,
            conflicts=conflicts,
            ctx=ctx,
        )

        retrieved_tokens = estimate_tokens(packed_md)
        baseline_tokens = (
            int(full_history_tokens)
            if full_history_tokens is not None
            else self._compute_full_history_tokens(ctx.project_id, retrieved_tokens)
        )
        savings_pct = (
            round(max(0.0, 100.0 * (1.0 - (retrieved_tokens / baseline_tokens))), 2)
            if baseline_tokens > 0
            else 0.0
        )
        latency_ms = max(1, (time.perf_counter_ns() - start_ns) // 1_000_000)

        self._record_session_metric(
            session_id=session_id,
            query=query,
            retrieved_tokens=retrieved_tokens,
            full_history_tokens=baseline_tokens,
            savings_pct=savings_pct,
            latency_ms=latency_ms,
        )

        return {
            "context": packed_md,
            "abstained": has_value_conflict or bool(conflicts),
            "conflicts": conflicts,
            "handover": handover,
            "memories_returned": len(decisions_and_constraints) + len(failed_attempts) + len(global_prefs),
            "retrieved_tokens": retrieved_tokens,
            "full_history_tokens": baseline_tokens,
            "savings_pct": savings_pct,
            "latency_ms": latency_ms,
            "project_id": ctx.project_id,
            "branch": ctx.branch,
        }

    def _fetch_latest_handover(self, project_id: str, branch: str) -> dict[str, Any] | None:
        rows = self.db.query(
            """
            MATCH (h:Handover)-[:FOR_PROJECT]->(p:Project {id: $project_id})
            WHERE h.status IN ['open', 'claimed']
              AND (h.branch = $branch OR h.branch = '*')
            RETURN h.id AS id,
                   h.branch AS branch,
                   h.status AS status,
                   h.agent_name AS agent_name,
                   h.claimed_by_agent AS claimed_by_agent,
                   h.summary AS summary,
                   h.next_steps AS next_steps,
                   h.blockers AS blockers,
                   h.base_commit AS base_commit,
                   h.dirty_files AS dirty_files
            ORDER BY h.created_at DESC
            LIMIT 1;
            """,
            {"project_id": project_id, "branch": branch},
        )
        return rows[0] if rows else None

    def _hybrid_search(self, query: str, ctx: GitContext, limit: int = 15) -> list[dict[str, Any]]:
        query_vec = self._embed(query)
        fts_scores: dict[str, float] = {}
        sanitized_q = _sanitize_fts_query(query)
        if self.db.fts_enabled and sanitized_q:
            try:
                fts_rows = self.db.query(
                    """
                    CALL QUERY_FTS_INDEX('Memory', 'memory_fts', $q)
                    RETURN node.id AS id, score AS score;
                    """,
                    {"q": sanitized_q},
                )
                max_score = max((float(r["score"]) for r in fts_rows), default=1.0) or 1.0
                for row in fts_rows:
                    fts_scores[row["id"]] = float(row["score"]) / max_score
            except Exception:
                fts_scores = {}

        allowed_branches = list({ctx.branch, "*", ctx.default_branch})
        project_rows = self.db.query(
            """
            MATCH (m:Memory)-[:IN_PROJECT]->(p:Project {id: $project_id})
            WHERE m.status = 'active'
              AND m.tainted = false
              AND m.branch IN $branches
              AND (m.valid_until IS NULL OR m.valid_until > current_timestamp())
              AND NOT EXISTS { MATCH (m)<-[:SUPERSEDES {branch: $branch}]-() }
              AND NOT EXISTS { MATCH (m)<-[:SUPERSEDES {branch: '*'}]-() }
            OPTIONAL MATCH (m)-[:ABOUT]->(t:Topic)
            RETURN m.id AS id,
                   m.scope AS scope,
                   m.branch AS branch,
                   m.kind AS kind,
                   m.subject_key AS subject_key,
                   m.title AS title,
                   m.content AS content,
                   m.authority AS authority,
                   m.confidence AS confidence,
                   t.id AS topic_id,
                   array_cosine_similarity(m.embedding, CAST($qvec AS FLOAT[384])) AS vec_sim;
            """,
            {
                "project_id": ctx.project_id,
                "branches": allowed_branches,
                "branch": ctx.branch,
                "qvec": query_vec,
            },
        )
        global_rows = self.db.query(
            """
            MATCH (m:Memory)
            WHERE m.scope = 'global'
              AND m.status = 'active'
              AND m.tainted = false
              AND (m.valid_until IS NULL OR m.valid_until > current_timestamp())
              AND NOT EXISTS { MATCH (m)<-[:SUPERSEDES {branch: '*'}]-() }
            OPTIONAL MATCH (m)-[:ABOUT]->(t:Topic)
            RETURN m.id AS id,
                   m.scope AS scope,
                   m.branch AS branch,
                   m.kind AS kind,
                   m.subject_key AS subject_key,
                   m.title AS title,
                   m.content AS content,
                   m.authority AS authority,
                   m.confidence AS confidence,
                   t.id AS topic_id,
                   array_cosine_similarity(m.embedding, CAST($qvec AS FLOAT[384])) AS vec_sim;
            """,
            {"qvec": query_vec},
        )

        # Deduplicate rows in case a Memory links to multiple Topics
        by_id: dict[str, dict[str, Any]] = {}
        query_terms = set(sanitized_q.lower().split())
        for row in [*project_rows, *global_rows]:
            mid = row["id"]
            if mid in by_id:
                continue
            vec_sim = float(row.get("vec_sim") or 0.0)
            bm25 = fts_scores.get(mid, 0.0)
            # Small lexical boost if query mentions exact subject_key or topic_id
            haystack = f"{row.get('topic_id', '')} {row['subject_key']} {row['title']} {row['content']}".lower()
            lexical_hits = sum(1 for tok in query_terms if tok in haystack)
            lexical_boost = min(0.25, 0.08 * lexical_hits)
            # Prefer branch-specific override over default branch
            branch_boost = 0.08 if row["branch"] == ctx.branch else 0.0
            hybrid_score = (0.55 * max(0.0, vec_sim)) + (0.45 * bm25) + lexical_boost + branch_boost
            if vec_sim >= 0.28 or bm25 > 0.0 or lexical_hits > 0:
                enriched = dict(row)
                enriched["vec_sim"] = vec_sim
                enriched["bm25"] = bm25
                enriched["score"] = hybrid_score
                by_id[mid] = enriched

        all_sorted = sorted(by_id.values(), key=lambda r: r["score"], reverse=True)
        if not all_sorted:
            return []

        # Adaptive relevance: keep top matches and items within reasonable proximity of top score
        top_score = all_sorted[0]["score"]
        cutoff = max(0.32, top_score * 0.55)
        ranked = [
            r for r in all_sorted
            if r["score"] >= cutoff or r.get("bm25", 0.0) > 0.0 or any(t in r["subject_key"].lower() for t in query_terms)
        ]
        return ranked[:limit]

    def _fetch_linked_constraints_and_failures(
        self,
        candidate_ids: list[str],
        ctx: GitContext,
    ) -> list[dict[str, Any]]:
        if not candidate_ids:
            return []
        allowed_branches = list({ctx.branch, "*", ctx.default_branch})
        rows = self.db.query(
            """
            MATCH (src:Memory)-[:ABOUT]->(t:Topic)<-[:ABOUT]-(linked:Memory)-[:IN_PROJECT]->(p:Project {id: $project_id})
            WHERE src.id IN $candidate_ids
              AND linked.id <> src.id
              AND linked.status = 'active'
              AND linked.tainted = false
              AND linked.kind IN ['constraint', 'failed_attempt']
              AND linked.branch IN $branches
              AND (linked.valid_until IS NULL OR linked.valid_until > current_timestamp())
              AND NOT EXISTS { MATCH (linked)<-[:SUPERSEDES {branch: $branch}]-() }
              AND NOT EXISTS { MATCH (linked)<-[:SUPERSEDES {branch: '*'}]-() }
            RETURN DISTINCT linked.id AS id,
                   linked.scope AS scope,
                   linked.branch AS branch,
                   linked.kind AS kind,
                   linked.subject_key AS subject_key,
                   linked.title AS title,
                   linked.content AS content,
                   linked.authority AS authority,
                   linked.confidence AS confidence,
                   t.id AS topic_id;
            """,
            {
                "candidate_ids": candidate_ids,
                "project_id": ctx.project_id,
                "branches": allowed_branches,
                "branch": ctx.branch,
            },
        )
        return rows

    def _fetch_global_preferences(self, limit: int = 5) -> list[dict[str, Any]]:
        return self.db.query(
            """
            MATCH (m:Memory)
            WHERE m.scope = 'global'
              AND m.kind = 'preference'
              AND m.status = 'active'
              AND m.tainted = false
              AND (m.valid_until IS NULL OR m.valid_until > current_timestamp())
            RETURN m.id AS id,
                   m.scope AS scope,
                   m.branch AS branch,
                   m.kind AS kind,
                   m.subject_key AS subject_key,
                   m.title AS title,
                   m.content AS content,
                   m.authority AS authority,
                   m.confidence AS confidence
            ORDER BY m.created_at DESC
            LIMIT $limit;
            """,
            {"limit": limit},
        )

    def _fetch_unresolved_conflicts(self, memory_ids: list[str]) -> list[dict[str, Any]]:
        if not memory_ids:
            return []
        rows = self.db.query(
            """
            MATCH (n:Memory)-[c:CONFLICTS_WITH]->(o:Memory)
            WHERE c.resolution_status = 'unresolved'
              AND (n.id IN $ids OR o.id IN $ids)
              AND n.status <> 'deleted'
              AND o.status <> 'deleted'
            RETURN DISTINCT n.id AS new_id,
                   n.title AS new_title,
                   n.content AS new_content,
                   n.authority AS new_authority,
                   n.status AS new_status,
                   n.subject_key AS subject_key,
                   o.id AS old_id,
                   o.title AS old_title,
                   o.content AS old_content,
                   o.authority AS old_authority,
                   o.status AS old_status,
                   c.conflict_type AS conflict_type;
            """,
            {"ids": memory_ids},
        )
        return rows

    def _pack_context(
        self,
        *,
        token_budget: int,
        handover: dict[str, Any] | None,
        decisions: list[dict[str, Any]],
        failures: list[dict[str, Any]],
        preferences: list[dict[str, Any]],
        conflicts: list[dict[str, Any]],
        ctx: GitContext,
    ) -> str:
        """Pack sections strictly in priority order within token_budget."""
        header = f"# Knowledge Brain Context ({ctx.project_name} @ {ctx.branch})"
        used_tokens = estimate_tokens(header)
        sections: list[str] = [header]

        def try_append_section(title: str, lines: list[str], cap_tokens: int) -> None:
            nonlocal used_tokens
            if not lines:
                return
            remaining = token_budget - used_tokens
            if remaining <= 12:
                return
            effective_cap = min(cap_tokens, remaining)
            heading = f"\n## {title}"
            heading_toks = estimate_tokens(heading)
            if heading_toks >= effective_cap:
                return
            kept: list[str] = [heading]
            section_toks = heading_toks
            for line in lines:
                ltoks = estimate_tokens(line)
                if section_toks + ltoks <= effective_cap:
                    kept.append(line)
                    section_toks += ltoks
            if len(kept) > 1:
                sections.extend(kept)
                used_tokens += section_toks

        # 1. Latest Open Handover (~200 tokens, highest priority)
        if handover:
            dirty = ", ".join(handover.get("dirty_files") or []) or "clean"
            ho_lines = [
                f"- **Agent**: `{handover['agent_name']}` (status: `{handover['status']}`, commit: `{handover.get('base_commit') or 'none'}`)",
                f"- **Summary**: {handover['summary']}",
                f"- **Next Steps**: {handover['next_steps']}",
            ]
            if handover.get("blockers"):
                ho_lines.append(f"- **Blockers**: {handover['blockers']}")
            ho_lines.append(f"- **Dirty Files**: {dirty}")
            try_append_section("Open Handover", ho_lines, max(200, int(token_budget * 0.25)))

        # 5 (reserved early when present so abstentions are never truncated): Conflict Warnings / Abstentions
        if conflicts:
            conflict_lines: list[str] = [
                "- **ABSTENTION / CONFLICT DETECTED**: I don't know which conflicting record is final; user confirmation required instead of guessing."
            ]
            for c in conflicts:
                conflict_lines.append(
                    f"- **[{c['conflict_type']}] `{c['subject_key']}`**: "
                    f"Option A (`{c['old_authority']}`, `{c['old_status']}`): {c['old_title']} — {c['old_content']} "
                    f"**VS** Option B (`{c['new_authority']}`, `{c['new_status']}`): {c['new_title']} — {c['new_content']}"
                )
            try_append_section(
                "Conflict Warnings & Abstention",
                conflict_lines,
                max(260, int(token_budget * 0.35)),
            )

        # 2. Direct Active Decisions & Constraints (~500 tokens)
        dec_lines = [
            f"- **[{m['kind']} | `{m['subject_key']}` | {m['authority']}] {m['title']}**: {m['content']}"
            for m in decisions
        ]
        try_append_section(
            "Active Decisions & Constraints",
            dec_lines,
            max(500, int(token_budget * 0.45)),
        )

        # 3. Failed Attempts & Blockers (~300 tokens)
        fail_lines = [
            f"- **[failed_attempt | `{m['subject_key']}`] {m['title']}**: {m['content']}"
            for m in failures
        ]
        try_append_section(
            "Failed Attempts & Blockers",
            fail_lines,
            max(300, int(token_budget * 0.25)),
        )

        # 4. Global Preferences (~100 tokens)
        pref_lines = [
            f"- **[preference | `{m['subject_key']}`] {m['title']}**: {m['content']}"
            for m in preferences
        ]
        try_append_section(
            "Global Preferences",
            pref_lines,
            max(100, token_budget - used_tokens),
        )

        if len(sections) == 1:
            sections.append("\n_No active memories or open handovers matched this query._")

        return "\n".join(sections)

    def _compute_full_history_tokens(self, project_id: str, retrieved_tokens: int) -> int:
        mem_rows = self.db.query(
            """
            MATCH (m:Memory)
            WHERE m.status <> 'deleted'
            RETURN m.title AS title, m.content AS content;
            """
        )
        src_rows = self.db.query("MATCH (s:Source) RETURN s.excerpt AS excerpt;")
        ho_rows = self.db.query(
            """
            MATCH (h:Handover)-[:FOR_PROJECT]->(p:Project {id: $project_id})
            RETURN h.summary AS summary, h.next_steps AS next_steps, h.blockers AS blockers;
            """,
            {"project_id": project_id},
        )
        total = 0
        for row in mem_rows:
            total += estimate_tokens(f"{row['title']} {row['content']}")
        for row in src_rows:
            total += estimate_tokens(row.get("excerpt") or "")
        for row in ho_rows:
            total += estimate_tokens(
                f"{row.get('summary') or ''} {row.get('next_steps') or ''} {row.get('blockers') or ''}"
            )
        return max(retrieved_tokens, total)

    def _record_session_metric(
        self,
        *,
        session_id: str,
        query: str,
        retrieved_tokens: int,
        full_history_tokens: int,
        savings_pct: float,
        latency_ms: int,
    ) -> None:
        metric_id = generate_uuidv7()
        self.db.query(
            """
            CREATE (:SessionMetric {
                id: $id,
                session_id: $session_id,
                query: $query,
                retrieved_tokens: $retrieved_tokens,
                full_history_tokens: $full_history_tokens,
                savings_pct: $savings_pct,
                latency_ms: $latency_ms,
                created_at: current_timestamp()
            });
            """,
            {
                "id": metric_id,
                "session_id": session_id or "default",
                "query": query[:300],
                "retrieved_tokens": retrieved_tokens,
                "full_history_tokens": full_history_tokens,
                "savings_pct": savings_pct,
                "latency_ms": latency_ms,
            },
        )

    # ------------------------------------------------------------------
    # Tool 3: handoff
    # ------------------------------------------------------------------

    def handoff(
        self,
        summary: str,
        next_steps: str,
        blockers: str = "",
        agent_name: str = "antigravity",
        status: str = "open",
        session_id: str = "",
        workspace_path: str | Path | None = None,
    ) -> dict[str, Any]:
        """Save an agent-to-agent checkpoint enriched with live Git HEAD and dirty files."""
        status_norm = status.strip().lower()
        if status_norm not in VALID_HANDOVER_STATUSES:
            raise ValueError(
                f"Invalid handover status '{status}'. Expected one of {sorted(VALID_HANDOVER_STATUSES)}"
            )

        ctx = get_git_context(workspace_path)
        self._ensure_project(ctx)
        handover_id = generate_uuidv7()
        source_id = generate_uuidv7()
        event_id = generate_uuidv7()
        dirty_list = list(ctx.dirty_files)
        excerpt = truncate_excerpt(f"{summary} | Next: {next_steps}")

        active_mem_rows = self.db.query(
            """
            MATCH (m:Memory)-[:IN_PROJECT]->(p:Project {id: $project_id})
            WHERE m.status = 'active'
              AND m.tainted = false
              AND (m.branch = $branch OR m.branch = '*')
            RETURN m.id AS id
            ORDER BY m.created_at DESC
            LIMIT 10;
            """,
            {"project_id": ctx.project_id, "branch": ctx.branch},
        )

        self.db.query("BEGIN TRANSACTION;")
        try:
            self.db.query(
                """
                CREATE (:Handover {
                    id: $id,
                    branch: $branch,
                    status: $status,
                    agent_name: $agent_name,
                    claimed_by_agent: NULL,
                    summary: $summary,
                    next_steps: $next_steps,
                    blockers: $blockers,
                    base_commit: $base_commit,
                    dirty_files: $dirty_files,
                    created_at: current_timestamp(),
                    updated_at: current_timestamp()
                });
                """,
                {
                    "id": handover_id,
                    "branch": ctx.branch,
                    "status": status_norm,
                    "agent_name": agent_name,
                    "summary": summary.strip(),
                    "next_steps": next_steps.strip(),
                    "blockers": blockers.strip(),
                    "base_commit": ctx.head_commit,
                    "dirty_files": dirty_list,
                },
            )
            self.db.query(
                """
                MATCH (h:Handover {id: $handover_id}), (p:Project {id: $project_id})
                CREATE (h)-[:FOR_PROJECT]->(p);
                """,
                {"handover_id": handover_id, "project_id": ctx.project_id},
            )
            for row in active_mem_rows:
                self.db.query(
                    """
                    MATCH (h:Handover {id: $handover_id}), (m:Memory {id: $memory_id})
                    CREATE (h)-[:RELATES_TO]->(m);
                    """,
                    {"handover_id": handover_id, "memory_id": row["id"]},
                )
            self.db.query(
                """
                CREATE (:Source {
                    id: $source_id,
                    source_type: 'agent_summary',
                    origin_trust: 'local_code',
                    tainted: false,
                    agent_name: $agent_name,
                    session_id: $session_id,
                    excerpt: $excerpt,
                    external_ref: $external_ref,
                    created_at: current_timestamp()
                });
                """,
                {
                    "source_id": source_id,
                    "agent_name": agent_name,
                    "session_id": session_id,
                    "excerpt": excerpt,
                    "external_ref": ctx.head_commit,
                },
            )
            self.db.query(
                """
                MATCH (h:Handover {id: $handover_id}), (s:Source {id: $source_id})
                CREATE (h)-[:SUPPORTED_BY]->(s);
                """,
                {"handover_id": handover_id, "source_id": source_id},
            )
            self.db.query(
                """
                CREATE (:Event {
                    id: $event_id,
                    event_type: 'HANDOVER_CREATED',
                    actor: $actor,
                    summary: $summary,
                    created_at: current_timestamp()
                });
                """,
                {
                    "event_id": event_id,
                    "actor": agent_name,
                    "summary": summary.strip()[:300],
                },
            )
            self.db.query(
                """
                MATCH (e:Event {id: $event_id}), (h:Handover {id: $handover_id})
                CREATE (e)-[:AFFECTED]->(h);
                """,
                {"event_id": event_id, "handover_id": handover_id},
            )
            self.db.query("COMMIT;")
        except Exception:
            self.db.query("ROLLBACK;")
            raise

        return {
            "status": "handover_ready",
            "handover_id": handover_id,
            "branch": ctx.branch,
            "base_commit": ctx.head_commit,
            "dirty_files": dirty_list,
            "project_id": ctx.project_id,
        }

    def claim_handover(self, handover_id: str, agent_name: str) -> dict[str, Any]:
        """Claim an open handover so two agents cannot pick up the same checkpoint."""
        rows = self.db.query(
            """
            MATCH (h:Handover {id: $id})
            RETURN h.status AS status, h.claimed_by_agent AS claimed_by_agent;
            """,
            {"id": handover_id},
        )
        if not rows:
            return {"status": "not_found", "handover_id": handover_id}
        if rows[0]["status"] != "open":
            return {
                "status": "already_claimed",
                "handover_id": handover_id,
                "claimed_by_agent": rows[0]["claimed_by_agent"],
            }

        event_id = generate_uuidv7()
        self.db.query("BEGIN TRANSACTION;")
        try:
            self.db.query(
                """
                MATCH (h:Handover {id: $id})
                SET h.status = 'claimed',
                    h.claimed_by_agent = $agent_name,
                    h.updated_at = current_timestamp();
                """,
                {"id": handover_id, "agent_name": agent_name},
            )
            self.db.query(
                """
                CREATE (:Event {
                    id: $event_id,
                    event_type: 'HANDOVER_CLAIMED',
                    actor: $actor,
                    summary: $summary,
                    created_at: current_timestamp()
                });
                """,
                {
                    "event_id": event_id,
                    "actor": agent_name,
                    "summary": f"Handover {handover_id} claimed by {agent_name}",
                },
            )
            self.db.query(
                """
                MATCH (e:Event {id: $event_id}), (h:Handover {id: $id})
                CREATE (e)-[:AFFECTED]->(h);
                """,
                {"event_id": event_id, "id": handover_id},
            )
            self.db.query("COMMIT;")
        except Exception:
            self.db.query("ROLLBACK;")
            raise
        return {"status": "claimed", "handover_id": handover_id, "claimed_by_agent": agent_name}

    # ------------------------------------------------------------------
    # Tool 4: forget
    # ------------------------------------------------------------------

    def forget(
        self,
        target: str,
        workspace_path: str | Path | None = None,
    ) -> dict[str, Any]:
        """Cascading redaction across Memory, Source, and Handover with 0-leak verification."""
        target_clean = target.strip()
        if not target_clean:
            raise ValueError("forget() target must be a non-empty string")

        mem_matches = self.db.query(
            """
            MATCH (m:Memory)
            WHERE m.status <> 'deleted'
              AND (
                lower(m.title) CONTAINS lower($target)
                OR lower(m.content) CONTAINS lower($target)
                OR lower(m.subject_key) CONTAINS lower($target)
              )
            RETURN m.id AS id;
            """,
            {"target": target_clean},
        )
        mem_ids = [r["id"] for r in mem_matches]

        # Also catch any Source nodes supporting those memories or directly matching target
        src_matches = self.db.query(
            """
            MATCH (s:Source)
            WHERE lower(s.excerpt) CONTAINS lower($target)
            RETURN s.id AS id;
            """,
            {"target": target_clean},
        )
        linked_src_matches = (
            self.db.query(
                """
                MATCH (m:Memory)-[:SUPPORTED_BY]->(s:Source)
                WHERE m.id IN $mem_ids
                RETURN s.id AS id;
                """,
                {"mem_ids": mem_ids},
            )
            if mem_ids
            else []
        )
        src_ids = list({r["id"] for r in [*src_matches, *linked_src_matches]})

        ho_matches = self.db.query(
            """
            MATCH (h:Handover)
            WHERE lower(h.summary) CONTAINS lower($target)
               OR lower(h.next_steps) CONTAINS lower($target)
               OR lower(h.blockers) CONTAINS lower($target)
            RETURN h.id AS id, h.summary AS summary, h.next_steps AS next_steps, h.blockers AS blockers;
            """,
            {"target": target_clean},
        )

        pattern = re.compile(re.escape(target_clean), re.IGNORECASE)
        event_id = generate_uuidv7()

        self.db.query("BEGIN TRANSACTION;")
        try:
            for mid in mem_ids:
                self.db.query(
                    """
                    MATCH (m:Memory {id: $id})
                    SET m.status = 'deleted',
                        m.subject_key = 'redacted',
                        m.title = '[REDACTED]',
                        m.content = '[REDACTED_BY_USER_REQUEST]',
                        m.embedding = CAST($zero_vec AS FLOAT[384]),
                        m.deleted_at = current_timestamp(),
                        m.deleted_reason = 'explicit_forget',
                        m.updated_at = current_timestamp();
                    """,
                    {"id": mid, "zero_vec": ZERO_VECTOR},
                )

            for sid in src_ids:
                self.db.query(
                    """
                    MATCH (s:Source {id: $id})
                    SET s.excerpt = '[REDACTED_PROVENANCE]';
                    """,
                    {"id": sid},
                )

            for ho in ho_matches:
                self.db.query(
                    """
                    MATCH (h:Handover {id: $id})
                    SET h.summary = $summary,
                        h.next_steps = $next_steps,
                        h.blockers = $blockers,
                        h.updated_at = current_timestamp();
                    """,
                    {
                        "id": ho["id"],
                        "summary": pattern.sub("[REDACTED]", ho.get("summary") or ""),
                        "next_steps": pattern.sub("[REDACTED]", ho.get("next_steps") or ""),
                        "blockers": pattern.sub("[REDACTED]", ho.get("blockers") or ""),
                    },
                )

            self.db.query(
                """
                CREATE (:Event {
                    id: $event_id,
                    event_type: 'FORGOTTEN',
                    actor: 'user',
                    summary: $summary,
                    created_at: current_timestamp()
                });
                """,
                {
                    "event_id": event_id,
                    "summary": f"Redacted {len(mem_ids)} memories, {len(src_ids)} sources, {len(ho_matches)} handovers",
                },
            )
            for mid in mem_ids:
                self.db.query(
                    """
                    MATCH (e:Event {id: $event_id}), (m:Memory {id: $id})
                    CREATE (e)-[:AFFECTED]->(m);
                    """,
                    {"event_id": event_id, "id": mid},
                )
            for ho in ho_matches:
                self.db.query(
                    """
                    MATCH (e:Event {id: $event_id}), (h:Handover {id: $id})
                    CREATE (e)-[:AFFECTED]->(h);
                    """,
                    {"event_id": event_id, "id": ho["id"]},
                )
            self.db.query("COMMIT;")
        except Exception:
            self.db.query("ROLLBACK;")
            raise

        # Step 3: Post-Deletion Verification (DB scan + live recall check)
        remaining_mem = self.db.query(
            """
            MATCH (m:Memory)
            WHERE m.status <> 'deleted'
              AND (
                lower(m.title) CONTAINS lower($target)
                OR lower(m.content) CONTAINS lower($target)
                OR lower(m.subject_key) CONTAINS lower($target)
              )
            RETURN count(m) AS cnt;
            """,
            {"target": target_clean},
        )
        remaining_src = self.db.query(
            """
            MATCH (s:Source)
            WHERE lower(s.excerpt) CONTAINS lower($target)
            RETURN count(s) AS cnt;
            """,
            {"target": target_clean},
        )
        remaining_ho = self.db.query(
            """
            MATCH (h:Handover)
            WHERE lower(h.summary) CONTAINS lower($target)
               OR lower(h.next_steps) CONTAINS lower($target)
               OR lower(h.blockers) CONTAINS lower($target)
            RETURN count(h) AS cnt;
            """,
            {"target": target_clean},
        )
        leak_count = (
            int(remaining_mem[0]["cnt"])
            + int(remaining_src[0]["cnt"])
            + int(remaining_ho[0]["cnt"])
        )

        recall_probe = self.recall(query=target_clean, workspace_path=workspace_path)
        recall_leaked = target_clean.lower() in recall_probe["context"].lower()

        return {
            "status": "success",
            "scrubbed_memories": len(mem_ids),
            "scrubbed_sources": len(src_ids),
            "scrubbed_handovers": len(ho_matches),
            "verification_passed": (leak_count == 0 and not recall_leaked),
        }

    def get_metrics_summary(self) -> dict[str, Any]:
        """Aggregate recorded SessionMetric rows."""
        rows = self.db.query(
            """
            MATCH (s:SessionMetric)
            RETURN count(s) AS calls,
                   sum(s.retrieved_tokens) AS total_retrieved_tokens,
                   sum(s.full_history_tokens) AS total_full_history_tokens,
                   avg(s.savings_pct) AS avg_savings_pct,
                   avg(s.latency_ms) AS avg_latency_ms;
            """
        )
        return rows[0] if rows else {}
