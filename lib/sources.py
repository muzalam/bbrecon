"""Git operations on bounty-targets-data + JSON snapshot reading."""

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone


# Platform file mapping
PLATFORM_FILES = {
    "hackerone": "data/hackerone_data.json",
    "bugcrowd": "data/bugcrowd_data.json",
    "intigriti": "data/intigriti_data.json",
    "yeswehack": "data/yeswehack_data.json",
}


def _run(cmd, cwd=None):
    result = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{result.stderr}")
    return result.stdout


def clone_repo(repo_url, dest):
    """Clone the bounty-targets-data repo (shallow for speed)."""
    if os.path.isdir(os.path.join(dest, ".git")):
        print(f"  Repo already exists at {dest}, pulling...")
        _run(["git", "pull", "--ff-only"], cwd=dest)
    else:
        parent = os.path.dirname(dest)
        os.makedirs(parent, exist_ok=True)
        # Shallow clone with enough history for diffing
        _run(["git", "clone", "--depth", "200", repo_url, dest])
    return dest


def pull_repo(repo_dir):
    """Pull latest changes."""
    _run(["git", "pull", "--ff-only"], cwd=repo_dir)


def deepen_history(repo_dir, commits=200):
    """Fetch more history if needed for longer time windows."""
    try:
        _run(["git", "fetch", "--deepen", str(commits)], cwd=repo_dir)
    except RuntimeError:
        pass  # Already have full history


def parse_since(since_str):
    """Parse '24h', '7d', '1w' into a timedelta."""
    unit = since_str[-1].lower()
    value = int(since_str[:-1])
    if unit == "h":
        return timedelta(hours=value)
    elif unit == "d":
        return timedelta(days=value)
    elif unit == "w":
        return timedelta(weeks=value)
    raise ValueError(f"Unknown time unit: {since_str}")


def find_baseline_commit(repo_dir, since_str):
    """Find the oldest commit within the time window."""
    delta = parse_since(since_str)
    cutoff = datetime.now(timezone.utc) - delta
    cutoff_iso = cutoff.strftime("%Y-%m-%dT%H:%M:%S")

    # Get the oldest commit after the cutoff
    try:
        output = _run(
            ["git", "log", "--reverse", "--format=%H", f"--since={cutoff_iso}", "--"],
            cwd=repo_dir,
        )
        commits = output.strip().split("\n")
        commits = [c for c in commits if c]
        if commits:
            return commits[0]
    except RuntimeError:
        pass

    # Fallback: use HEAD~N based on rough hourly commits
    hours = delta.total_seconds() / 3600
    n = max(1, int(hours))  # ~1 commit per hour
    try:
        output = _run(["git", "rev-parse", f"HEAD~{n}"], cwd=repo_dir)
        return output.strip()
    except RuntimeError:
        return "HEAD~1"


def read_json_at_commit(repo_dir, commit, filepath):
    """Read a JSON file at a specific git commit."""
    try:
        output = _run(["git", "show", f"{commit}:{filepath}"], cwd=repo_dir)
        return json.loads(output)
    except (RuntimeError, json.JSONDecodeError):
        return []


def read_current_json(repo_dir, filepath):
    """Read a JSON file at HEAD."""
    return read_json_at_commit(repo_dir, "HEAD", filepath)


def get_snapshots(repo_dir, platform, since_str):
    """Return (baseline_data, current_data) for a platform."""
    filepath = PLATFORM_FILES.get(platform)
    if not filepath:
        raise ValueError(f"Unknown platform: {platform}")

    baseline_commit = find_baseline_commit(repo_dir, since_str)
    baseline = read_json_at_commit(repo_dir, baseline_commit, filepath)
    current = read_current_json(repo_dir, filepath)
    return baseline, current
