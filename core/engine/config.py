"""Project configuration loader.

Loads project.yaml, overlay, and credentials for a given project and environment.
All paths are resolved relative to the project root.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

# Path prefixes injected by Git Bash / MSYS when it mangles ``/Workspace/...``
# arguments at command-invocation time. A real Databricks workspace path never
# lives under these — if we see one, the user set the env var from Git Bash
# and Bash transformed the leading slash.
_MSYS_MANGLE_PREFIXES = (
    "C:/Program Files/Git/",
    "C:/Program Files (x86)/Git/",
    "C:/msys64/",
)


def _check_msys_mangled_path(value: str, key: str) -> None:
    """Raise if a workspace-like path looks MSYS-mangled.

    Triggers only when the value starts with a known MSYS install prefix AND
    contains ``/Workspace/`` or ``/Shared/`` further down — the combined
    signature of a Bash-converted Databricks path. Other coincidental matches
    (e.g. a real local file under Git's install dir) are left alone.
    """
    if not isinstance(value, str):
        return
    norm = value.replace("\\", "/")
    for prefix in _MSYS_MANGLE_PREFIXES:
        if not norm.startswith(prefix):
            continue
        if "/Workspace/" not in norm and "/Shared/" not in norm:
            continue
        unmangled = "/" + norm[len(prefix):]
        raise ValueError(
            f"{key} appears to be Git-Bash-mangled:\n"
            f"  Current value: {value!r}\n"
            f"  Probable intent: {unmangled!r}\n"
            f"  Cause: a path like /Workspace/... was set from Git Bash, "
            f"which converts leading-slash arguments to Windows paths via "
            f"MSYS path translation.\n"
            f"  Fix: re-set the env var from PowerShell or cmd (setx), not "
            f"from Git Bash. To keep using Git Bash, run "
            f"`MSYS_NO_PATHCONV=1 setx VAR /Workspace/...` instead."
        )


class ProjectConfig:
    """Loaded configuration for a project."""

    def __init__(self, project_root: Path, raw: dict):
        self.root = project_root
        self.raw = raw
        self.name: str = raw["project"]["name"]
        self.client: str = raw["project"]["client"]
        self.description: str = raw["project"].get("description", "")
        self.environments: dict = raw.get("environments", {})
        self.platforms: dict = raw.get("platforms", {})
        self.scopes: dict = raw.get("scopes", {})
        self.patch_max_age_days: int = raw.get("patch_max_age_days", 7)
        skills_raw = raw.get("skills") or {}
        include = skills_raw.get("include")
        self.skills_include: list[str] | None = list(include) if include else None

    def is_skill_included(self, skill_name: str) -> bool:
        """Return True if the named skill belongs in this distribution.

        Used by ``/ops-publish`` to filter ``.claude/commands/`` at publish-time.
        ``skills_include = None`` means include-all (backward compat for lab
        distributions that don't pre-curate their skill set). An explicit list
        activates whitelist mode: only listed skills are published.
        """
        if self.skills_include is None:
            return True
        return skill_name in self.skills_include

    def env_names(self) -> list[str]:
        return list(self.environments.keys())

    def env_config(self, env: str) -> dict:
        if env not in self.environments:
            raise ValueError(f"Unknown environment: {env}. Available: {self.env_names()}")
        return self.environments[env]

    def overlay_path(self, env: str) -> Path:
        env_cfg = self.env_config(env)
        rel = env_cfg.get("overlay", f"overlays/{env}.yaml")
        return self.root / rel

    def state_dir(self, env: str, scope: str | None = None) -> Path:
        base = self.root / "state" / env
        return base / scope if scope else base

    def src_dir(self, scope: str) -> Path:
        scope_cfg = self.scopes.get(scope, {})
        rel = scope_cfg.get("path", f"src/{scope}")
        return self.root / rel

    def patches_dir(self, env: str) -> Path:
        return self.root / "patches" / env

    def connector_for_scope(self, scope: str) -> str:
        scope_cfg = self.scopes.get(scope, {})
        return scope_cfg.get("connector", scope)


def load_project(project_root: Path | str) -> ProjectConfig:
    """Load project.yaml from a project directory."""
    project_root = Path(project_root).resolve()
    config_path = project_root / "config" / "project.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"No project.yaml found at {config_path}")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    # Non-strict: project.yaml may reference vars only needed by some envs;
    # the per-env overlay is what enforces strict resolution at operation time.
    raw = _resolve_env_vars(raw, strict=False)
    return ProjectConfig(project_root, raw)


def load_overlay(project_root: Path | str, env: str) -> dict:
    """Load overlay YAML for a specific environment."""
    project_root = Path(project_root).resolve()
    # Try project.yaml overlay path first
    config_path = project_root / "config" / "project.yaml"
    if config_path.exists():
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        envs = raw.get("environments", {})
        if env in envs:
            rel = envs[env].get("overlay", f"overlays/{env}.yaml")
            overlay_path = project_root / rel
        else:
            overlay_path = project_root / "overlays" / f"{env}.yaml"
    else:
        overlay_path = project_root / "overlays" / f"{env}.yaml"

    if not overlay_path.exists():
        raise FileNotFoundError(f"Overlay not found: {overlay_path}")
    raw = yaml.safe_load(overlay_path.read_text(encoding="utf-8"))
    # Non-strict: the overlay may reference env vars only needed by some
    # scopes (e.g. workspace_id for fabric vs notebooks for databricks).
    # Operations on one scope must not fail because a variable used by a
    # different scope is unset. The consuming connector is expected to
    # detect literal ``${`` in the values it reads and raise a precise
    # error at use-time. Matches the policy used by load_credentials().
    return _resolve_env_vars(raw, strict=False)


def load_credentials(project_root: Path | str) -> dict:
    """Load credentials.yaml from project config directory.

    Resolves ${ENV_VAR} references in string values. Unresolved references
    are left as literal ``${VAR}`` (non-strict) so callers that only need a
    subset of platforms (e.g. ``--scope power_bi``) are not blocked by an
    unset variable used by a different connector (e.g. ``DATABRICKS_TOKEN``).
    The consuming connector is expected to detect literal ``${`` and raise
    a precise error at use-time.
    """
    project_root = Path(project_root).resolve()
    creds_path = project_root / "config" / "credentials.yaml"
    if not creds_path.exists():
        example = creds_path.with_name("credentials.example.yaml")
        hint = (
            f"Copy {example.name} to credentials.yaml and fill in your credentials."
            if example.exists()
            else "Create credentials.yaml from the framework template."
        )
        raise FileNotFoundError(f"No credentials.yaml found at {creds_path}. {hint}")
    raw = yaml.safe_load(creds_path.read_text(encoding="utf-8"))
    return _resolve_env_vars(raw, strict=False)


def _resolve_env_vars(
    obj: dict | list | str, *, strict: bool = True
) -> dict | list | str:
    """Recursively resolve ${ENV_VAR} references in config values.

    Supports both whole-string (``${VAR}``) and inline (``${VAR}/suffix``)
    substitution.

    Args:
        obj: Object to resolve (dict, list, or str — others pass through).
        strict: If True, raise ``EnvironmentError`` when a referenced variable
            is not set. If False, leave the literal ``${VAR}`` in place so the
            caller can defer the error to actual use.
    """
    if isinstance(obj, str):
        def _sub(match: re.Match) -> str:
            var_name = match.group(1)
            value = os.environ.get(var_name)
            if value is None:
                if strict:
                    raise EnvironmentError(f"Environment variable not set: {var_name}")
                return match.group(0)
            _check_msys_mangled_path(value, f"${{{var_name}}}")
            return value
        return _ENV_VAR_PATTERN.sub(_sub, obj)
    if isinstance(obj, dict):
        return {k: _resolve_env_vars(v, strict=strict) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_env_vars(v, strict=strict) for v in obj]
    return obj
