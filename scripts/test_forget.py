import sys
import os

sys.path.insert(0, r"c:\Users\ASUS\Documents\files\hackathon\devhost")
from brain.db import Database
from brain.memory_service import MemoryService

db_path = r"C:\Users\ASUS\.cortex\cortex.kuzu"
db = Database(db_path)
service = MemoryService(db)

target = "TEST_API_KEY_998877_FORGET_DEMO"

print("=" * 60)
print(f"[*] TESTING CORTEX FORGET CALL ON: {target}")
print("=" * 60)

# 1. Recall before forget
res_before = service.recall(target)
found_before = target in res_before["context"]
print(f"1. Context before deletion:")
print(f"   Target present in graph: {found_before}")

# 2. Execute forget
forget_res = service.forget(target)
print(f"\n2. Executed forget('{target}'):")
print(f"   Status:              {forget_res['status']}")
print(f"   Scrubbed memories:   {forget_res['scrubbed_memories']}")
print(f"   Scrubbed handovers:  {forget_res['scrubbed_handovers']}")
print(f"   Verification passed: {forget_res['verification_passed']}")
print(f"   Remaining leaks:     {forget_res['leak_count']}")

# 3. Recall after forget
res_after = service.recall(target)
found_after = target in res_after["context"]
print(f"\n3. Context after deletion:")
print(f"   Target present in graph: {found_after}")

# 4. Direct DB verification query
check_q = "MATCH (m:Memory) WHERE m.title CONTAINS 'Temporary' OR m.content CONTAINS $tgt RETURN count(m);"
cnt = db.execute(check_q, {"tgt": target}).get_next()[0]
print(f"   Direct DB query count matching target: {cnt}")

assert cnt == 0, "Error: Leaked data found in DB!"
assert not found_after, "Error: Leaked data found in recall context!"
assert forget_res["verification_passed"] is True, "Error: Verification failed!"

print("\n[SUCCESS] FORGET CALL VERIFIED 100% WITH ZERO LEAKS!")
print("=" * 60)
