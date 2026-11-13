import os
import sys
import shutil
import subprocess

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from brain.db import Database
from brain.memory_service import MemoryService
from brain.git_context import get_git_context

DEMO_REPO_PATH = os.path.abspath("./demo_git_project")
DEMO_DB_PATH = os.path.abspath("./demo_git_brain.kuzu")

def run_git(args, cwd=DEMO_REPO_PATH):
    res = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True, check=True)
    return res.stdout.strip()

def main():
    print("=" * 70)
    print("DEMO: HOW KNOWLEDGE BRAIN MANAGES TIMELINES WITH GIT")
    print("=" * 70)

    # Clean up prior test runs
    for path in [DEMO_REPO_PATH, DEMO_DB_PATH]:
        if os.path.exists(path):
            shutil.rmtree(path, ignore_errors=True)

    os.makedirs(DEMO_REPO_PATH, exist_ok=True)
    db = Database(DEMO_DB_PATH)
    service = MemoryService(db)

    # 1. Initialize a real Git repository
    print("\n[Step 1] Initializing a Git repository on branch 'main'...")
    run_git(["init", "-b", "main"])
    run_git(["config", "user.name", "AgentAlice"])
    run_git(["config", "user.email", "alice@devhost.ai"])

    # Create initial files and commit
    with open(os.path.join(DEMO_REPO_PATH, "app.py"), "w") as f:
        f.write("# Main application entrypoint\n")
    run_git(["add", "app.py"])
    run_git(["commit", "-m", "Initial commit on main"])
    
    ctx_main = get_git_context(DEMO_REPO_PATH)
    print(f"  -> Repository ID:   {ctx_main['repo_id']}")
    print(f"  -> Active Branch:   {ctx_main['branch']}")
    print(f"  -> HEAD Commit:     {ctx_main['head_commit'][:8]}...")
    print(f"  -> Dirty Files:     {ctx_main['dirty_files']}")

    # 2. Record a baseline decision on main
    print("\n[Step 2] Recording architectural decision on 'main'...")
    service.remember(
        title="Use PostgreSQL for primary datastore",
        content="ACID transactions required for main ledger",
        topic="database",
        subject_key="primary_db",
        repo_path=DEMO_REPO_PATH
    )
    print("  -> Recorded: PostgreSQL decision linked to branch 'main'.")

    # 3. Create a feature branch: feature/payment-gateway
    print("\n[Step 3] Creating and checking out branch 'feature/payment-gateway'...")
    run_git(["checkout", "-b", "feature/payment-gateway"])

    # Create uncommitted dirty work on disk
    payment_file = os.path.join(DEMO_REPO_PATH, "payment.py")
    with open(payment_file, "w") as f:
        f.write("# Stripe webhook handler (work in progress)\n")

    # 4. Agent calls handoff on the feature branch
    print("\n[Step 4] Agent calls handoff() while dirty files exist on disk...")
    # Notice: we DO NOT pass the file list manually! Git context discovers it live!
    handoff_res = service.handoff(
        summary="Drafted Stripe webhook handler skeleton.",
        next_steps="Implement webhook HMAC signature validation.",
        blockers="Need Stripe webhook secret key.",
        agent_name="AgentAlice",
        repo_path=DEMO_REPO_PATH
    )
    print(f"  -> Handover ID:     {handoff_res['handover_id'][:8]}...")
    print(f"  -> Branch Captured: {handoff_res['branch']}")
    print(f"  -> Dirty Files Captured Live: {handoff_res['dirty_files_captured']}")

    # 5. Record a branch-specific decision on the feature branch
    print("\n[Step 5] Recording a branch-specific decision on 'feature/payment-gateway'...")
    service.remember(
        title="Use Stripe Elements SDK",
        content="Prebuilt UI components reduce PCI compliance scope",
        topic="payments",
        subject_key="payment_ui",
        repo_path=DEMO_REPO_PATH
    )

    # 6. Test branch-aware context recall
    print("\n[Step 6] Testing Branch-Aware Context Recall...")
    print("--- RECALL ON 'feature/payment-gateway' ---")
    feat_recall = service.recall("database payment", repo_path=DEMO_REPO_PATH)
    print(feat_recall["context"])

    print("\n[Step 7] Switching back to 'main'...")
    # Discard dirty file to switch cleanly
    run_git(["checkout", "main"])
    print("--- RECALL ON 'main' ---")
    main_recall = service.recall("database payment", repo_path=DEMO_REPO_PATH)
    print(main_recall["context"])

    # Cleanup
    del service
    del db
    shutil.rmtree(DEMO_REPO_PATH, ignore_errors=True)
    shutil.rmtree(DEMO_DB_PATH, ignore_errors=True)
    print("\n" + "=" * 70)
    print("SUCCESS: GIT TIMELINE & BRANCH ISOLATION FULLY DEMONSTRATED!")
    print("=" * 70)

if __name__ == "__main__":
    main()
