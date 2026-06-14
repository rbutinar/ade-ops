"""ade-ops sync engine.

Core operations: pull, push, diff, status.
"""

from .config import ProjectConfig, load_project, load_overlay, load_credentials
from .operations import pull, push, diff, status
from .state import load_state, save_state, compute_hash, compute_file_hash
from .overlay import assemble_scope, apply_overlay_to_content, apply_patches

__all__ = [
    "ProjectConfig",
    "load_project",
    "load_overlay",
    "load_credentials",
    "pull",
    "push",
    "diff",
    "status",
    "load_state",
    "save_state",
    "compute_hash",
    "compute_file_hash",
    "assemble_scope",
    "apply_overlay_to_content",
    "apply_patches",
]
