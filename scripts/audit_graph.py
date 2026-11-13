import kuzu

db = kuzu.Database(r"C:\Users\ASUS\.knowledge-brain\brain.kuzu")
conn = kuzu.Connection(db)

def query(q, params=None):
    res = conn.execute(q, params) if params else conn.execute(q)
    rows = []
    while res.has_next():
        rows.append(res.get_next())
    return rows

print("=" * 65)
print("LEAN KNOWLEDGE BRAIN GRAPH REPORT")
print("=" * 65)
print("Total Memories:     ", query("MATCH (m:Memory) RETURN count(m)")[0][0])
print("Active Memories:    ", query("MATCH (m:Memory) WHERE m.status = 'active' RETURN count(m)")[0][0])
print("Superseded Memories:", query("MATCH (m:Memory) WHERE m.status = 'superseded' RETURN count(m)")[0][0])
print("Total Handovers:    ", query("MATCH (h:Handover) RETURN count(h)")[0][0])
print("Supersedes Edges:   ", query("MATCH ()-[r:SUPERSEDES]->() RETURN count(r)")[0][0])

print("\n--- ACTIVE TIMELINE IN GRAPH ---")
mems = query("MATCH (m:Memory) WHERE m.status = 'active' RETURN m.kind, m.title, m.topic")
for kind, title, topic in mems:
    print(f"• [{kind.upper()}] [{topic}] {title}")

print("\n--- SUPERSEDED LINEAGE ---")
supers = query("MATCH (new:Memory)-[r:SUPERSEDES]->(old:Memory) RETURN new.title, old.title, r.reason")
for new_t, old_t, reason in supers:
    print(f"• '{new_t}' -> SUPERSEDED -> '{old_t}' ({reason})")

print("=" * 65)
