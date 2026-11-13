"""Kuzu database connection, schema initialization, migrations, and invariants."""

from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path
from typing import Any

import kuzu

DEFAULT_DB_PATH = Path.home() / ".knowledge-brain" / "brain.kuzu"

VALID_SCOPES = frozenset({"global", "project"})
VALID_KINDS = frozenset({"decision", "constraint", "failed_attempt", "preference"})
VALID_STATUSES = frozenset(
    {"active", "proposed", "conflicted", "superseded", "deleted", "expired"}
)
VALID_AUTHORITIES = frozenset({"user", "verified", "agent"})
VALID_ORIGIN_TRUST = frozenset({"direct_user", "local_code", "external_untrusted"})
VALID_HANDOVER_STATUSES = frozenset({"open", "claimed", "completed", "abandoned"})
VALID_SOURCE_TYPES = frozenset(
    {"user_message", "tool_output", "git_commit", "hook", "agent_summary"}
)

MAX_EXCERPT_CHARS = 500

NODE_DDL = [
    """
    CREATE NODE TABLE IF NOT EXISTS Project (
        id STRING,
        name STRING,
        git_remote_url STRING,
        root_commit_hash STRING,
        local_paths STRING[],
        default_branch STRING,
        created_at TIMESTAMP,
        updated_at TIMESTAMP,
        PRIMARY KEY (id)
    )
    """,
    """
    CREATE NODE TABLE IF NOT EXISTS Topic (
        id STRING,
        display_name STRING,
        aliases STRING[],
        created_at TIMESTAMP,
        PRIMARY KEY (id)
    )
    """,
    """
    CREATE NODE TABLE IF NOT EXISTS Memory (
        id STRING,
        scope STRING,
        branch STRING,
        kind STRING,
        subject_key STRING,
        title STRING,
        content STRING,
        status STRING,
        authority STRING,
        confidence DOUBLE,
        embedding FLOAT[384],
        tainted BOOLEAN,
        origin_trust STRING,
        git_head_at_write STRING,
        valid_from TIMESTAMP,
        valid_until TIMESTAMP,
        deleted_at TIMESTAMP,
        deleted_reason STRING,
        content_hash STRING,
        created_at TIMESTAMP,
        updated_at TIMESTAMP,
        PRIMARY KEY (id)
    )
    """,
    """
    CREATE NODE TABLE IF NOT EXISTS Handover (
        id STRING,
        branch STRING,
        status STRING,
        agent_name STRING,
        claimed_by_agent STRING,
        summary STRING,
        next_steps STRING,
        blockers STRING,
        base_commit STRING,
        dirty_files STRING[],
        created_at TIMESTAMP,
        updated_at TIMESTAMP,
        PRIMARY KEY (id)
    )
    """,
    """
    CREATE NODE TABLE IF NOT EXISTS Source (
        id STRING,
        source_type STRING,
        origin_trust STRING,
        tainted BOOLEAN,
        agent_name STRING,
        session_id STRING,
        excerpt STRING,
        external_ref STRING,
        created_at TIMESTAMP,
        PRIMARY KEY (id)
    )
    """,
    """
    CREATE NODE TABLE IF NOT EXISTS Event (
        id STRING,
        event_type STRING,
        actor STRING,
        summary STRING,
        created_at TIMESTAMP,
        PRIMARY KEY (id)
    )
    """,
    """
    CREATE NODE TABLE IF NOT EXISTS SessionMetric (
        id STRING,
        session_id STRING,
        query STRING,
        retrieved_tokens INT64,
        full_history_tokens INT64,
        savings_pct DOUBLE,
        latency_ms INT64,
        created_at TIMESTAMP,
        PRIMARY KEY (id)
    )
    """,
]

REL_DDL = [
    "CREATE REL TABLE IF NOT EXISTS IN_PROJECT (FROM Memory TO Project)",
    "CREATE REL TABLE IF NOT EXISTS FOR_PROJECT (FROM Handover TO Project)",
    "CREATE REL TABLE IF NOT EXISTS ABOUT (FROM Memory TO Topic, relevance DOUBLE)",
    """
    CREATE REL TABLE IF NOT EXISTS SUPERSEDES (
        FROM Memory TO Memory,
        branch STRING,
        reason STRING,
        created_at TIMESTAMP
    )
    """,
    """
    CREATE REL TABLE IF NOT EXISTS CONFLICTS_WITH (
        FROM Memory TO Memory,
        conflict_type STRING,
        resolution_status STRING,
        detected_at TIMESTAMP
    )
    """,
    "CREATE REL TABLE IF NOT EXISTS RELATES_TO (FROM Handover TO Memory)",
    "CREATE REL TABLE IF NOT EXISTS SUPPORTED_BY (FROM Memory TO Source, FROM Handover TO Source)",
    "CREATE REL TABLE IF NOT EXISTS AFFECTED (FROM Event TO Memory, FROM Event TO Handover)",
]


def generate_uuidv7() -> str:
    """Generate a time-sortable RFC 9562 UUIDv7 string."""
    ms = time.time_ns() // 1_000_000
    rand = bytearray(os.urandom(10))
    ts_bytes = ms.to_bytes(6, "big")
    rand[0] = (rand[0] & 0x0F) | 0x70  # version 7
    rand[2] = (rand[2] & 0x3F) | 0x80  # variant RFC 4122
    raw = ts_bytes + bytes(rand)
    hex_str = raw.hex()
    return (
        f"{hex_str[0:8]}-{hex_str[8:12]}-{hex_str[12:16]}-"
        f"{hex_str[16:20]}-{hex_str[20:32]}"
    )


def canonicalize_topic_id(topic: str) -> str:
    """Normalize a topic slug: lowercase, trimmed, spaces/underscores -> hyphens."""
    cleaned = re.sub(r"[\s_]+", "-", (topic or "general").strip().lower())
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    return cleaned or "general"


def compute_content_hash(
    scope: str,
    branch: str,
    kind: str,
    subject_key: str,
    title: str,
) -> str:
    """Compute SHA-256 deduplication hash matching schema invariant."""
    payload = "|".join(
        [
            scope.strip().lower(),
            branch.strip(),
            kind.strip().lower(),
            subject_key.strip().lower(),
            " ".join(title.strip().lower().split()),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def truncate_excerpt(text: str | None, limit: int = MAX_EXCERPT_CHARS) -> str:
    """Enforce bounded Source.excerpt length."""
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def resolve_db_path(db_path: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the Kuzu database path from arg, env var, or default."""
    raw = db_path or os.environ.get("KNOWLEDGE_BRAIN_DB_PATH") or DEFAULT_DB_PATH
    return Path(raw).expanduser().resolve()


class BrainDatabase:
    """Manages Kuzu database lifecycle, DDL migrations, and FTS extension."""

    def __init__(self, db_path: str | os.PathLike[str] | None = None) -> None:
        self.db_path = resolve_db_path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = kuzu.Database(str(self.db_path))
        self.conn = kuzu.Connection(self.db)
        self.fts_enabled = False
        self.init_schema()

    def init_schema(self) -> None:
        """Create all node/relationship tables and ensure FTS extension + index exist."""
        for ddl in NODE_DDL:
            self.conn.execute(ddl)
        for ddl in REL_DDL:
            self.conn.execute(ddl)
        self._ensure_fts()

    def _ensure_fts(self) -> None:
        """Load Kuzu FTS extension and create memory_fts index if missing."""
        try:
            self.conn.execute("LOAD EXTENSION fts;")
        except Exception:
            try:
                self.conn.execute("INSTALL fts;")
                self.conn.execute("LOAD EXTENSION fts;")
            except Exception:
                self.fts_enabled = False
                return

        try:
            self.conn.execute(
                "CALL CREATE_FTS_INDEX('Memory', 'memory_fts', ['title', 'content']);"
            )
        except Exception as exc:
            msg = str(exc).lower()
            if "already exists" not in msg and "duplicate" not in msg:
                self.fts_enabled = False
                return
        self.fts_enabled = True

    def query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Execute a Cypher statement and return rows as list of dicts."""
        result = self.conn.execute(cypher, params or {})
        columns = result.get_column_names()
        rows: list[dict[str, Any]] = []
        while result.has_next():
            values = result.get_next()
            rows.append(dict(zip(columns, values)))
        return rows

    def close(self) -> None:
        """Close the Kuzu connection and database handle cleanly."""
        try:
            self.conn.close()
        except Exception:
            pass
        try:
            self.db.close()
        except Exception:
            pass

