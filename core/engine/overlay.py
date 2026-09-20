"""Overlay engine for ade-ops.

Applies environment-specific transforms to source files during push/diff.
Transforms are declarative, defined in overlay YAML files.

Supported transforms:
- catalog_remap: Replace catalog names in file content
- text_replace: Generic string replacements
- file_exclude: Exclude files by glob pattern
- pbi_model_overlay: Power BI semantic-model table/relationship exclusions
  and item renames (see pbi_overlay.py)
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

from .pbi_overlay import apply_pbi_model_overlay


# Dotfiles authored by ade-ops itself that must survive the src→assemble walk.
# Hidden filenames (starting with ``.``) are otherwise filtered out so that
# editor noise (``.DS_Store``, ``.git/``, ``.state.yaml``) never reaches a
# remote.
ADEOPS_SIDECARS = frozenset({".fabric.json"})


def apply_overlay_to_content(content: str, overlay: dict) -> str:
    """Apply overlay transforms to a single file's text content.

    Performs catalog remapping and generic text replacements.
    The overlay dict is expected to have this structure:

        databricks:
          catalog: target_catalog

        transforms:  # optional, explicit replacements
          - pattern: "old_text"
            replace: "new_text"

    Args:
        content: File content as string.
        overlay: Overlay configuration dict.

    Returns:
        Transformed content.
    """
    db = overlay.get("databricks", {})

    # Catalog remap: replace the base catalog with the target
    base_catalog = overlay.get("_base_catalog")
    target_catalog = db.get("catalog")
    if base_catalog and target_catalog and base_catalog != target_catalog:
        content = content.replace(base_catalog, target_catalog)

    # Explicit text transforms
    for transform in overlay.get("transforms", []):
        pattern = transform.get("pattern", "")
        replace = transform.get("replace", "")
        if pattern and pattern in content:
            content = content.replace(pattern, replace)

    return content


def should_exclude(path: str, overlay: dict) -> bool:
    """Check if a file should be excluded based on overlay rules.

    Args:
        path: Relative file path (e.g., "notebooks/setup/init.py").
        overlay: Overlay configuration dict.

    Returns:
        True if the file should be excluded.
    """
    excludes = overlay.get("exclude", [])
    for pattern in excludes:
        if fnmatch.fnmatch(path, pattern):
            return True
        # Also match against just the filename
        if fnmatch.fnmatch(Path(path).name, pattern):
            return True
    return False


def apply_patches(
    files: dict[str, bytes],
    patches_dir: Path,
) -> dict[str, bytes]:
    """Override file contents with patched versions.

    Patches are files in patches/{env}/{scope}/ that override the corresponding
    file in src/. If a patch exists for a path, it replaces the source content.
    New files in patches/ that don't exist in src/ are added.

    Args:
        files: Dict mapping relative paths to file content bytes.
        patches_dir: Path to patches/{env}/ directory.

    Returns:
        Updated files dict with patches applied.
    """
    if not patches_dir.exists():
        return files

    result = dict(files)
    patch_count = 0

    for fp in patches_dir.rglob("*"):
        if fp.is_dir() or fp.name.startswith("."):
            continue
        rel = fp.relative_to(patches_dir).as_posix()
        result[rel] = fp.read_bytes()
        patch_count += 1

    if patch_count:
        print(f"  [PATCH] Applied {patch_count} patches from {patches_dir}")

    return result


def assemble_scope(
    src_dir: Path,
    overlay: dict,
    patches_dir: Path | None = None,
    *,
    apply_excludes: bool = True,
) -> dict[str, bytes]:
    """Assemble files for a scope: read src/ + apply overlay + apply patches.

    This is the core assembly pipeline used by push and diff.

    Args:
        src_dir: Path to src/{scope}/ directory.
        overlay: Overlay configuration dict.
        patches_dir: Optional path to patches/{env}/{scope}/ directory.
        apply_excludes: When True (default) overlay ``exclude`` globs drop
            matching files. Set False when the caller passes an explicit file
            filter — an explicit target means the operator deliberately wants
            those files (e.g. a normally-excluded ``_setup/*`` seeder pushed
            once), so the exclude must not pre-empt the filter. The filter
            itself is the narrowing safety.

    Returns:
        Dict mapping relative paths to final file content bytes.
    """
    files: dict[str, bytes] = {}

    if not src_dir.exists():
        return files

    # 1. Read source files
    for fp in sorted(src_dir.rglob("*")):
        if fp.is_dir():
            continue
        if fp.name.startswith(".") and fp.name not in ADEOPS_SIDECARS:
            continue
        rel = fp.relative_to(src_dir).as_posix()

        # Check exclusions (skipped when an explicit filter is driving the op)
        if apply_excludes and should_exclude(rel, overlay):
            continue

        files[rel] = fp.read_bytes()

    # 2. Apply content transforms
    transformed: dict[str, bytes] = {}
    for rel, content in files.items():
        try:
            text = content.decode("utf-8")
            text = apply_overlay_to_content(text, overlay)
            transformed[rel] = text.encode("utf-8")
        except UnicodeDecodeError:
            # Binary file — no text transforms
            transformed[rel] = content

    # 3. Apply Power BI semantic-model overlay (table/relationship exclusions,
    #    item renames). No-op for non-PBI scopes and when nothing is declared.
    transformed = apply_pbi_model_overlay(transformed, overlay)

    # 4. Apply patches
    if patches_dir:
        transformed = apply_patches(transformed, patches_dir)

    return transformed
