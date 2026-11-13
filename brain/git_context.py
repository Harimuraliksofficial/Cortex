import subprocess
import os
import hashlib
from typing import Dict, List, Optional

def get_git_context(repo_path: Optional[str] = None) -> Dict:
    """
    Fast discovery of Git context for the target workspace.
    Minimizes subprocess overhead by batching lookups.
    """
    target_dir = os.path.abspath(repo_path) if repo_path else os.getcwd()

    # Fast check: run rev-parse to get toplevel and branch in a single call
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--show-toplevel", "--abbrev-ref", "HEAD", "HEAD"],
            cwd=target_dir,
            capture_output=True,
            text=True,
            timeout=2,
            check=False
        )
        if res.returncode != 0:
            raise FileNotFoundError("Not a git repository")

        lines = res.stdout.strip().splitlines()
        root_path = os.path.abspath(lines[0])
        branch = lines[1] if len(lines) > 1 and lines[1] != "HEAD" else "main"
        head_commit = lines[2] if len(lines) > 2 else ""

        # Status check for dirty files
        status_res = subprocess.run(
            ["git", "status", "--short"],
            cwd=root_path,
            capture_output=True,
            text=True,
            timeout=2,
            check=False
        )
        dirty_files = []
        if status_res.returncode == 0 and status_res.stdout.strip():
            for line in status_res.stdout.strip().splitlines():
                parts = line.strip().split(maxsplit=1)
                if len(parts) == 2:
                    dirty_files.append(parts[1])

        # Canonical repo_id derived from root path or origin
        repo_id = hashlib.sha256(root_path.lower().encode("utf-8")).hexdigest()[:16]
        repo_name = os.path.basename(root_path)

        return {
            "repo_id": repo_id,
            "repo_name": repo_name,
            "branch": branch,
            "head_commit": head_commit,
            "dirty_files": dirty_files,
            "is_git": True,
            "root_path": root_path
        }
    except Exception:
        # Non-git folder fallback
        folder_hash = hashlib.sha256(target_dir.lower().encode("utf-8")).hexdigest()[:12]
        return {
            "repo_id": f"local-{folder_hash}",
            "repo_name": os.path.basename(target_dir),
            "branch": "__default__",
            "head_commit": None,
            "dirty_files": [],
            "is_git": False,
            "root_path": target_dir
        }
