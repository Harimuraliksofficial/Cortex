"""Read-only Git context extractor for Knowledge Brain."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GitContext:
    """Snapshot of the workspace's Git identity and working-tree state."""

    project_id: str
    project_name: str
    repo_root: str
    branch: str
    is_git_repo: bool
    git_remote_url: str | None = None
    root_commit_hash: str | None = None
    head_commit: str | None = None
    default_branch: str = "main"
    dirty_files: tuple[str, ...] = ()


def _run_git(args: list[str], cwd: Path) -> str | None:
    """Run a read-only git command and return stripped stdout, or None on failure."""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    output = proc.stdout.strip()
    return output if output else None


def normalize_remote_url(raw_url: str | None) -> str | None:
    """Normalize a Git remote URL across SSH/HTTPS variants."""
    if not raw_url:
        return None
    url = raw_url.strip()
    # Strip embedded userinfo like https://token@github.com/org/repo
    url = re.sub(r"^(https?://)[^/@]+@", r"\1", url)
    # Normalize git@host:org/repo.git -> host/org/repo
    ssh_match = re.match(r"^(?:ssh://)?(?:[^@]+@)?([^:/]+):(.+?)(?:\.git)?/?$", url)
    if ssh_match and "://" not in url:
        host, path = ssh_match.groups()
        return f"{host.lower()}/{path.strip('/').lower()}"
    url = re.sub(r"^https?://", "", url, flags=re.IGNORECASE)
    url = re.sub(r"\.git$", "", url, flags=re.IGNORECASE)
    return url.rstrip("/").lower()


def _stable_project_id(seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"proj_{digest}"


def get_git_context(workspace_path: str | os.PathLike[str] | None = None) -> GitContext:
    """Inspect the local workspace via read-only git subprocess calls."""
    cwd = Path(workspace_path or os.environ.get("KNOWLEDGE_BRAIN_WORKSPACE") or os.getcwd()).resolve()
    if not cwd.exists():
        cwd = Path.cwd().resolve()

    top_level = _run_git(["rev-parse", "--show-toplevel"], cwd)
    if not top_level:
        canonical_path = str(cwd).replace("\\", "/").lower()
        return GitContext(
            project_id=_stable_project_id(f"path:{canonical_path}"),
            project_name=cwd.name or "workspace",
            repo_root=str(cwd),
            branch="__default__",
            is_git_repo=False,
        )

    repo_root = str(Path(top_level).resolve())
    remote_raw = _run_git(["config", "--get", "remote.origin.url"], cwd)
    normalized_remote = normalize_remote_url(remote_raw)

    root_commits = _run_git(["rev-list", "--max-parents=0", "HEAD"], cwd)
    root_commit_hash = root_commits.splitlines()[0].strip() if root_commits else None

    head_commit = _run_git(["rev-parse", "HEAD"], cwd)
    branch = _run_git(["branch", "--show-current"], cwd)
    if not branch:
        if head_commit:
            branch = f"detached@{head_commit[:8]}"
        else:
            branch = "main"

    origin_head = _run_git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd)
    default_branch = origin_head.split("/", 1)[-1] if origin_head and "/" in origin_head else "main"

    # Read status without stripping leading space of the first line, only trailing newlines
    dirty_files: list[str] = []
    try:
        status_proc = subprocess.run(
            ["git", "status", "--short"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if status_proc.returncode == 0:
            for line in status_proc.stdout.splitlines():
                cleaned = line.strip()
                if cleaned:
                    dirty_files.append(cleaned)
    except (OSError, subprocess.SubprocessError):
        pass

    if normalized_remote:
        id_seed = f"remote:{normalized_remote}"
    elif root_commit_hash:
        id_seed = f"root:{root_commit_hash}"
    else:
        id_seed = f"path:{repo_root.replace(chr(92), '/').lower()}"

    return GitContext(
        project_id=_stable_project_id(id_seed),
        project_name=Path(repo_root).name or "repo",
        repo_root=repo_root,
        branch=branch,
        is_git_repo=True,
        git_remote_url=normalized_remote,
        root_commit_hash=root_commit_hash,
        head_commit=head_commit,
        default_branch=default_branch,
        dirty_files=tuple(dirty_files),
    )
