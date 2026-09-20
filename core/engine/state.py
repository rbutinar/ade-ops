"""State tracking for ade-ops.

Manages .state.yaml files that record what was pulled from remote environments.
Each scope (notebooks, power_bi) within each environment has its own state file.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import yaml


def compute_hash(content: bytes) -> str:
    """SHA256 hash of content, truncated for readability."""
    return f"sha256:{hashlib.sha256(content).hexdigest()[:16]}"


def compute_file_hash(path: Path) -> str:
    """SHA256 hash of a file's content."""
    return compute_hash(path.read_bytes())


def load_state(state_dir: Path) -> dict | None:
    """Load .state.yaml from a state directory.

    Returns None if the state file doesn't exist.
    """
    state_file = state_dir / ".state.yaml"
    if not state_file.exists():
        return None
    return yaml.safe_load(state_file.read_text(encoding="utf-8"))


def save_state(state_dir: Path, env: str, files: list[dict]) -> Path:
    """Write .state.yaml with sync metadata.

    Args:
        state_dir: Directory to write the state file to.
        env: Environment name (e.g., "cert", "prod").
        files: List of file entries, each with at minimum:
            - path: str (relative path within scope)
            - hash: str (content hash)

    Returns:
        Path to the written state file.
    """
    state = {
        "last_pull": datetime.now(timezone.utc).isoformat(),
        "environment": env,
        "files": files,
    }
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / ".state.yaml"
    state_file.write_text(
        yaml.dump(state, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    return state_file


def format_age(dt_str: str) -> str:
    """Format an ISO datetime string as a human-readable relative age."""
    try:
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        if delta.days == 0:
            hours = delta.seconds // 3600
            if hours == 0:
                minutes = delta.seconds // 60
                return f"{minutes}m ago"
            return f"{hours}h ago"
        elif delta.days == 1:
            return "yesterday"
        else:
            return f"{delta.days}d ago"
    except (ValueError, TypeError):
        return "unknown"
