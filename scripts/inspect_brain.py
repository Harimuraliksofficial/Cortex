"""CLI inspector for Knowledge Brain (Kuzu Graph DB).

Usage:
    python scripts/inspect_brain.py
    python scripts/inspect_brain.py --topic database
    python scripts/inspect_brain.py --target "STRIPE"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from brain.db import BrainDatabase, resolve_db_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect Knowledge Brain Kuzu Graph Database.")
    parser.add_argument("--db-path", default=None, help="Path to brain.kuzu database folder")
    parser.add_argument("--topic", default=None, help="Filter memories by topic ID")
    parser.add_argument("--all", action="store_true", help="Include superseded and deleted records")
    args = parser.parse_args()

    db_path = resolve_db_path(args.db_path)
    print(f"\n=======================================================")
    print(f" Knowledge Brain Inspector: {db_path}")
    print(f"=======================================================\n")

    if not db_path.exists():
        print(f"No database directory found at {db_path} yet.")
        print("Run `python scripts/benchmark_30.py` or invoke `remember` via MCP to initialize it.\n")
        return

    db = BrainDatabase(db_path=db_path)

    # 1. Overview counts
    counts = {}
    for table in ["Project", "Topic", "Memory", "Handover", "Source", "Event", "SessionMetric"]:
        try:
            res = db.query(f"MATCH (n:{table}) RETURN count(n) AS cnt;")
            counts[table] = res[0]["cnt"] if res else 0
        except Exception:
            counts[table] = 0

    print("--- Graph Node Summary ---")
    for tbl, count in counts.items():
        print(f"  {tbl:<15}: {count}")
    print()

    # 2. Memories listing
    where_clauses = []
    if not args.all:
        where_clauses.append("m.status = 'active'")
    if args.topic:
        where_clauses.append("t.id = $topic")

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    params = {"topic": args.topic} if args.topic else {}

    query = f"""
    MATCH (m:Memory)
    OPTIONAL MATCH (m)-[:ABOUT]->(t:Topic)
    {where_sql}
    RETURN m.id AS id,
           m.status AS status,
           m.authority AS authority,
           m.kind AS kind,
           m.branch AS branch,
           m.subject_key AS subject_key,
           m.title AS title,
           m.content AS content,
           t.id AS topic
    ORDER BY m.created_at DESC;
    """
    memories = db.query(query, params)
    print(f"--- Memories ({len(memories)} shown, filter: {'all' if args.all else 'active only'}) ---")
    if not memories:
        print("  (No memories found)")
    for mem in memories:
        status_tag = f"[{mem['status'].upper()}]" if mem["status"] != "active" else ""
        print(f"  * {status_tag} [{mem['authority']} | {mem['kind']}] ({mem['subject_key']}) on branch '{mem['branch']}'")
        print(f"    Title: {mem['title']}")
        print(f"    Why:   {mem['content'][:140]}{'...' if len(mem['content']) > 140 else ''}")
        print()

    # 3. Open Handovers
    handovers = db.query(
        """
        MATCH (h:Handover)
        WHERE h.status IN ['open', 'claimed']
        RETURN h.id AS id, h.branch AS branch, h.status AS status, h.agent_name AS agent,
               h.summary AS summary, h.next_steps AS next_steps, h.dirty_files AS dirty_files
        ORDER BY h.created_at DESC LIMIT 5;
        """
    )
    print(f"--- Active / Open Handovers ({len(handovers)}) ---")
    if not handovers:
        print("  (No open handovers)")
    for ho in handovers:
        print(f"  * [{ho['status'].upper()}] Agent: {ho['agent']} (branch: {ho['branch']})")
        print(f"    Summary:    {ho['summary']}")
        print(f"    Next Steps: {ho['next_steps']}")
        print(f"    Dirty:      {', '.join(ho.get('dirty_files') or []) or 'none'}")
        print()

    db.close()


if __name__ == "__main__":
    main()

