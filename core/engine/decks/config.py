"""Per-seat ``decks.yaml`` config loader with env-var resolution.

The file lives at ``<repo_root>/config/decks.yaml`` and is gitignored
(analogous to ``credentials.yaml``). It maps template *pack* names to
folders that hold brand ``.pptx`` files, typically under OneDrive.

Example::

    template_paths:
      community: "${OneDrive}/60. ADE - Community/templates/decks"
      accenture: "${OneDriveCommercial}/60. ADE - <organization>/templates/decks/_base"
    default_pack: accenture
    output_dir: "${OneDrive}/60. ADE - Community/drafts/decks"

``${VAR}`` references are resolved from ``os.environ``. An unresolved
reference raises ``DecksConfigError`` — there is no silent fallback to
``None``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class DecksConfigError(Exception):
    """Raised when ``decks.yaml`` is missing, malformed, or references an
    environment variable that is not set."""


_ENV_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _resolve_env_vars(value: str) -> str:
    """Substitute ``${VAR}`` occurrences with ``os.environ[VAR]``.

    Raises ``DecksConfigError`` if any referenced variable is unset.
    """
    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        var_name = match.group(1)
        resolved = os.environ.get(var_name)
        if resolved is None:
            missing.append(var_name)
            return ""
        return resolved

    result = _ENV_VAR_RE.sub(replace, value)
    if missing:
        raise DecksConfigError(
            f"Environment variable(s) not set: {', '.join(missing)}. "
            "On Windows, OneDrive sync sets ${OneDrive} and ${OneDriveCommercial} "
            "automatically when the corresponding OneDrive account is signed in."
        )
    return result


def _find_repo_root(start: Path) -> Path:
    """Walk up from ``start`` looking for a directory that holds ``config/``
    plus either ``.git`` or a ``CLAUDE.md`` (the lab's two canonical
    root markers)."""
    cur = start.resolve()
    for _ in range(20):
        if (cur / ".git").exists() or (cur / "CLAUDE.md").exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    raise DecksConfigError(
        f"Cannot locate repo root from {start}: no ancestor has ``.git`` or "
        "``CLAUDE.md``. Run the command from inside the ade-ops repo."
    )


@dataclass
class DecksConfig:
    """Resolved per-seat deck config.

    ``template_paths`` values are already env-var-resolved to absolute
    paths but are NOT checked for existence — call sites that need a
    template surface a precise error if the pack folder is missing.
    """

    template_paths: dict[str, Path] = field(default_factory=dict)
    default_pack: str | None = None
    output_dir: Path | None = None
    config_path: Path | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def pack_path(self, pack_name: str) -> Path:
        """Return the resolved folder for a pack name.

        Raises ``DecksConfigError`` if the pack is not declared in
        ``decks.yaml.template_paths``.
        """
        if pack_name not in self.template_paths:
            available = ", ".join(sorted(self.template_paths)) or "(none)"
            raise DecksConfigError(
                f"Unknown template pack '{pack_name}'. Declared packs: {available}"
            )
        return self.template_paths[pack_name]


def load_decks_config(repo_root: Path | None = None) -> DecksConfig:
    """Load ``<repo_root>/config/decks.yaml`` and resolve env-var paths.

    If ``repo_root`` is not given, walks up from ``Path.cwd()`` looking
    for the lab's canonical markers (``.git`` or ``CLAUDE.md``).
    """
    if repo_root is None:
        repo_root = _find_repo_root(Path.cwd())
    config_path = repo_root / "config" / "decks.yaml"
    if not config_path.exists():
        example = repo_root / "config" / "decks.yaml.example"
        hint = (
            f"Copy ``{example.relative_to(repo_root)}`` to "
            f"``{config_path.relative_to(repo_root)}`` and edit it."
            if example.exists()
            else "Create the file following ``core/conventions/deck-template.md``."
        )
        raise DecksConfigError(f"No deck config at {config_path}. {hint}")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise DecksConfigError(
            f"{config_path}: top-level YAML must be a mapping, got "
            f"{type(raw).__name__}"
        )

    template_paths: dict[str, Path] = {}
    for pack_name, path_value in (raw.get("template_paths") or {}).items():
        if not isinstance(path_value, str):
            raise DecksConfigError(
                f"{config_path}: template_paths[{pack_name!r}] must be a string"
            )
        template_paths[pack_name] = Path(_resolve_env_vars(path_value))

    default_pack = raw.get("default_pack")
    if default_pack is not None and default_pack not in template_paths:
        raise DecksConfigError(
            f"{config_path}: default_pack='{default_pack}' is not declared in "
            f"template_paths"
        )

    output_dir = None
    if raw.get("output_dir"):
        output_dir = Path(_resolve_env_vars(raw["output_dir"]))

    return DecksConfig(
        template_paths=template_paths,
        default_pack=default_pack,
        output_dir=output_dir,
        config_path=config_path,
        raw=raw,
    )
