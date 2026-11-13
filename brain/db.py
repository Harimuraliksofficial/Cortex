import os
import kuzu
from typing import Optional, Dict, Any

DEFAULT_DB_PATH = os.path.expanduser("~/.cortex/cortex.kuzu")

LEAN_DDL = [
    # 1. Memory node: Active decisions, constraints, failed attempts
    """
    CREATE NODE TABLE IF NOT EXISTS Memory (
        id STRING,
        repo_id STRING,
        branch STRING,
        kind STRING,
        topic STRING,
        subject_key STRING,
        title STRING,
        content STRING,
        status STRING,
        authority STRING,
        conflict_with STRING,
        created_at TIMESTAMP,
        updated_at TIMESTAMP,
        PRIMARY KEY (id)
    );
    """,

    # 2. Handover node: Session checkpoints with live uncommitted files
    """
    CREATE NODE TABLE IF NOT EXISTS Handover (
        id STRING,
        repo_id STRING,
        branch STRING,
        status STRING,
        agent_name STRING,
        summary STRING,
        next_steps STRING,
        blockers STRING,
        dirty_files STRING[],
        created_at TIMESTAMP,
        PRIMARY KEY (id)
    );
    """,

    # 3. Supersession relationship: Explicit lineage when a decision replaces another
    """
    CREATE REL TABLE IF NOT EXISTS SUPERSEDES (
        FROM Memory TO Memory,
        reason STRING,
        created_at TIMESTAMP
    );
    """
]

class Database:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self.db = kuzu.Database(self.db_path)
        self.conn = kuzu.Connection(self.db)
        self._init_schema()

    def _init_schema(self):
        for stmt in LEAN_DDL:
            cleaned = stmt.strip()
            if cleaned:
                try:
                    self.conn.execute(cleaned)
                except Exception as e:
                    if "already exists" not in str(e).lower():
                        print(f"Schema notice: {e}")

    def execute(self, query: str, parameters: Optional[Dict[str, Any]] = None):
        if parameters:
            return self.conn.execute(query, parameters)
        return self.conn.execute(query)

    def close(self):
        global _instance
        try:
            if hasattr(self, "conn"):
                del self.conn
            if hasattr(self, "db"):
                del self.db
        except Exception:
            pass
        _instance = None

_instance: Optional[Database] = None

def get_db(db_path: Optional[str] = None) -> Database:
    global _instance
    if _instance is None or (db_path and _instance.db_path != db_path):
        _instance = Database(db_path)
    return _instance
