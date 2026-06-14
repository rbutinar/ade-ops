"""Core operations for ade-ops: pull, push, diff, status.

These are the orchestration functions that coordinate connectors, overlays,
state tracking, and file I/O. Each operation is connector-agnostic — the
actual platform interaction is delegated to the connector passed in.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import hashlib

from .config import ProjectConfig, load_overlay
from .overlay import assemble_scope
from .state import compute_file_hash, format_age, load_state, save_state


def _write_if_changed(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` only when the on-disk bytes differ.

    Pull is otherwise non-idempotent: rewriting a byte-identical file bumps its
    mtime, which makes git report unchanged pulled files as ``modified``
    (stat-dirty). On a real seat this drowned 9 genuine diffs under 180 phantom
    ones. Skipping the write when content is unchanged keeps both the bytes and
    the mtime stable, so ``git status`` after a no-op pull stays clean.
    """
    if path.exists() and path.read_bytes() == data:
        return
    path.write_bytes(data)


# =============================================================================
# Pull — download remote state into state/{env}/{scope}/
# =============================================================================

def pull(
    config: ProjectConfig,
    env: str,
    scope: str,
    connector,
    *,
    pipeline_filter: str | None = None,
) -> list[dict]:
    """Pull remote state into state/{env}/{scope}/.

    Downloads all objects from the remote environment and writes them
    to the local state directory. Updates .state.yaml with metadata.

    Args:
        config: Loaded project configuration.
        env: Target environment (e.g., "cert", "prod").
        scope: Asset scope (e.g., "notebooks", "power_bi").
        connector: Platform connector instance (implements PlatformConnector).
        pipeline_filter: Optional filter to pull only a specific pipeline/item.

    Returns:
        List of state file entries written.
    """
    overlay = load_overlay(config.root, env)
    state_dir = config.state_dir(env, scope)
    state_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"PULL — {env.upper()} / {scope}")
    print(f"{'='*60}")

    # Delegate to connector
    env_cfg = config.env_config(env)
    objects = connector.list_objects(env_cfg, overlay, pipeline_filter=pipeline_filter)

    state_files = []
    pulled = 0
    errors = 0

    for obj in objects:
        remote_path = obj["path"]
        rel_path = obj["local_path"]  # Relative path for local storage

        print(f"  [PULL] {rel_path}")
        content = connector.pull_object(remote_path)
        if content is None:
            print(f"  [ERROR] Failed: {remote_path}")
            errors += 1
            continue

        local_path = state_dir / rel_path

        if isinstance(content, dict):
            # Folder payload (e.g. PBIP / TMDL parts). Write each part
            # idempotently and prune only the parts no longer present, so
            # deletes still round-trip cleanly without rewriting unchanged
            # files (a blanket wipe-then-rewrite would churn every mtime).
            local_path.mkdir(parents=True, exist_ok=True)
            expected: set[Path] = set()
            hasher = hashlib.sha256()
            for sub_path in sorted(content):
                blob = content[sub_path]
                target = local_path / sub_path
                target.parent.mkdir(parents=True, exist_ok=True)
                _write_if_changed(target, blob)
                expected.add(target.resolve())
                hasher.update(sub_path.encode("utf-8"))
                hasher.update(b"\0")
                hasher.update(blob)
            # Prune stale entries (files removed remotely) so deletes round-trip;
            # unchanged files are left untouched. Empty dirs are pruned last.
            for stale in sorted(local_path.rglob("*"), reverse=True):
                if stale.is_file() and stale.resolve() not in expected:
                    stale.unlink()
                elif stale.is_dir():
                    try:
                        stale.rmdir()  # only succeeds if the dir is now empty
                    except OSError:
                        pass
            object_hash = f"sha256:{hasher.hexdigest()[:16]}"
            object_type = obj.get("type", "FOLDER")

            # Optional sibling files (e.g. .pbip Power BI project markers
            # so Power BI Desktop can open the pulled folder directly, or
            # an editor stub Report for SemanticModel folders). Connectors
            # opt in by exposing materialize_siblings(). Returned keys are
            # paths RELATIVE TO THE PARENT of the pulled folder; forward
            # slashes are allowed so a sibling can be a nested file inside
            # a generated folder. Siblings are intentionally NOT registered
            # in .state.yaml — they are locally-derived, not pulled.
            if hasattr(connector, "materialize_siblings") and callable(
                connector.materialize_siblings
            ):
                siblings = connector.materialize_siblings(local_path.name, content)
                for sibling_path, sibling_blob in siblings.items():
                    target = local_path.parent / sibling_path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    _write_if_changed(target, sibling_blob)
        else:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            content_bytes = content.encode("utf-8") if isinstance(content, str) else content
            _write_if_changed(local_path, content_bytes)
            object_hash = f"sha256:{hashlib.sha256(content_bytes).hexdigest()[:16]}"
            object_type = obj.get("type", "FILE")

        state_files.append({
            "path": f"{scope}/{rel_path}",
            "hash": object_hash,
            "remote_path": remote_path,
            "object_type": object_type,
            "remote_modified": obj.get("modified", datetime.now(timezone.utc).isoformat()),
        })
        pulled += 1

    # Save state
    state_path = save_state(state_dir, env, state_files)
    print(f"\n[TOTAL] {pulled} files pulled, {errors} errors")
    print(f"[STATE] {state_path.relative_to(config.root)}")
    print(f"{'='*60}")

    return state_files


# =============================================================================
# Push — assemble src + overlay + patches and upload to remote
# =============================================================================

@dataclass
class PushResult:
    """Outcome of a push operation, granular enough for accurate audit log.

    - ``pushed``: count of successfully uploaded units.
    - ``total``: count of units the connector attempted (or would attempt
      for dry-run).
    - ``failed_paths``: paths that returned False from ``push_object`` (or
      raised a per-unit exception caught by the connector).
    - ``dry_run``: True when no upload actually happened.

    The audit log convention: outcome = ``ok`` if pushed == total > 0,
    ``fail`` if pushed == 0 and total > 0, ``partial`` otherwise.
    ``empty`` if total == 0 (no files matched the filter).
    """

    pushed: int = 0
    total: int = 0
    failed_paths: list[str] = field(default_factory=list)
    dry_run: bool = False

    def __int__(self) -> int:
        # Backward compat with callers that treated the return as an int count.
        return self.pushed

    @property
    def outcome(self) -> str:
        if self.total == 0:
            return "empty"
        if self.pushed == self.total:
            return "ok"
        if self.pushed == 0:
            return "fail"
        return "partial"


def push(
    config: ProjectConfig,
    env: str,
    scope: str,
    connector,
    *,
    dry_run: bool = False,
    file_filter: str | None = None,
) -> "PushResult":
    """Push assembled local files to a remote environment.

    Assembly pipeline: src/ → overlay transforms → patches → upload.

    Args:
        config: Loaded project configuration.
        env: Target environment.
        scope: Asset scope.
        connector: Platform connector instance.
        dry_run: If True, show what would be pushed without uploading.
        file_filter: Optional filter to push only specific files.

    Returns:
        ``PushResult`` — caller (CLI) inspects ``outcome`` for accurate
        audit logging. Backward compatible with ``int(result)``.
    """
    overlay = load_overlay(config.root, env)
    src_dir = config.src_dir(scope)
    patches_dir = config.patches_dir(env) / scope

    print(f"\n{'='*60}")
    print(f"PUSH — {env.upper()} / {scope}{'  (DRY RUN)' if dry_run else ''}")
    print(f"{'='*60}")

    # Assemble files. An explicit filter bypasses overlay excludes so a
    # deliberately-excluded file (e.g. a `_setup/*` seeder) can be pushed once
    # by name — otherwise the exclude drops it before the filter is even seen.
    files = assemble_scope(
        src_dir, overlay, patches_dir, apply_excludes=(file_filter is None)
    )
    print(f"[ASSEMBLED] {len(files)} files from {src_dir.relative_to(config.root)}")

    if file_filter:
        files = {k: v for k, v in files.items() if file_filter in k}
        print(
            f"[FILTER] {len(files)} files matching '{file_filter}' "
            f"(overlay excludes bypassed — explicit filter)"
        )

    if not files:
        print("[SKIP] No files to push")
        return PushResult(pushed=0, total=0, dry_run=dry_run)

    env_cfg = config.env_config(env)
    pushed = 0
    failed_paths: list[str] = []

    # Some connectors (e.g. Fabric for Power BI) need files grouped into
    # per-item folders before push so the whole PBIP/TMDL bundle goes up in
    # one updateDefinition call. Connectors opt in by exposing group_files().
    if hasattr(connector, "group_files") and callable(connector.group_files):
        groups = connector.group_files(files)
        units = sorted(groups.items())
        unit_label = "item"
    else:
        units = [(rel, content) for rel, content in sorted(files.items())]
        unit_label = "file"

    for unit_path, payload in units:
        if dry_run:
            if isinstance(payload, dict):
                size = sum(len(b) for b in payload.values())
                detail = f"{len(payload)} parts, {size:,} bytes"
            else:
                detail = f"{len(payload):,} bytes"
            print(f"  [DRY RUN] {unit_path} ({detail})")
            # Connector-side routing preview (F11, 2026-05-24): show
            # the resolved target name + matched item id so the operator
            # can verify routing before the real push. Opt-in via the
            # preview_push() method on the connector (Fabric has it; the
            # Databricks connector does not need it, paths are explicit).
            if hasattr(connector, "preview_push") and callable(connector.preview_push):
                try:
                    preview = connector.preview_push(unit_path, payload, env_cfg, overlay)
                except Exception as e:
                    print(f"    target:  <preview failed: {e}>")
                else:
                    err = preview.get("error")
                    if err:
                        print(f"    target:  <unresolved: {err}>")
                    else:
                        target_name = preview.get("target_display_name") or "?"
                        target_ws = preview.get("target_workspace_id") or "?"
                        matched = preview.get("matched_existing_id")
                        action = (
                            f"update id={matched}" if matched else "create (new)"
                        )
                        print(
                            f"    target:  displayName={target_name!r} "
                            f"ws={target_ws} action={action}"
                        )
            continue

        print(f"  [PUSH] {unit_path}")
        success = connector.push_object(unit_path, payload, env_cfg, overlay)
        if success:
            pushed += 1
        else:
            print(f"  [ERROR] Failed to push: {unit_path}")
            failed_paths.append(str(unit_path))

    total_units = len(units)
    print(
        f"\n[TOTAL] {pushed if not dry_run else total_units} {unit_label}(s) "
        f"{'would be ' if dry_run else ''}pushed"
    )
    if failed_paths and not dry_run:
        print(f"[FAILED] {len(failed_paths)} {unit_label}(s) did not upload:")
        for p in failed_paths[:10]:
            print(f"  - {p}")
        if len(failed_paths) > 10:
            print(f"  ... and {len(failed_paths) - 10} more")
    print(f"{'='*60}")

    return PushResult(
        pushed=pushed if not dry_run else total_units,
        total=total_units,
        failed_paths=failed_paths,
        dry_run=dry_run,
    )


# =============================================================================
# Diff — compare assembled local vs remote state
# =============================================================================

def diff(
    config: ProjectConfig,
    env: str,
    scope: str,
    *,
    show_content: bool = True,
    file_filter: str | None = None,
) -> dict:
    """Compare assembled local files against pulled remote state.

    Requires a prior pull to populate state/{env}/{scope}/.

    Args:
        config: Loaded project configuration.
        env: Target environment.
        scope: Asset scope.
        show_content: If True, print unified diffs for modified files.
        file_filter: Optional filter for specific files.

    Returns:
        Dict with keys: added, removed, modified, identical (lists of paths).
    """
    overlay = load_overlay(config.root, env)
    src_dir = config.src_dir(scope)
    patches_dir = config.patches_dir(env) / scope
    state_dir = config.state_dir(env, scope)

    print(f"\n{'='*60}")
    print(f"DIFF — {env.upper()} / {scope}")
    print(f"{'='*60}")

    if not state_dir.exists():
        print(f"[WARN] No state for {env}/{scope}. Run pull first.")
        return {"added": [], "removed": [], "modified": [], "identical": []}

    # Assemble local
    # Symmetry with push: an explicit filter bypasses overlay excludes so a
    # filtered diff sees the same assembled set push would upload.
    local_files = assemble_scope(
        src_dir, overlay, patches_dir, apply_excludes=(file_filter is None)
    )

    # Collect state files. Skip:
    # - directories (we want files only)
    # - dotfiles (sidecar conventions: .fabric.json, .platform, etc.)
    # - editor stubs (*_editor.Report/ folders + *_editor.pbip files
    #   materialized for Power BI Desktop convenience — local-only, not
    #   part of the canonical content per #20 fabric-diff-path-symmetry)
    state_files: dict[str, bytes] = {}
    for fp in state_dir.rglob("*"):
        if fp.is_dir() or fp.name.startswith("."):
            continue
        rel_posix = fp.relative_to(state_dir).as_posix()
        if "_editor." in rel_posix or rel_posix.endswith(".pbip"):
            continue
        state_files[rel_posix] = fp.read_bytes()

    # Apply filter
    if file_filter:
        local_files = {k: v for k, v in local_files.items() if file_filter in k}
        state_files = {k: v for k, v in state_files.items() if file_filter in k}

    # Compare
    all_paths = sorted(set(local_files.keys()) | set(state_files.keys()))
    added = []
    removed = []
    modified = []
    identical = []

    for path in all_paths:
        in_local = path in local_files
        in_state = path in state_files

        if in_local and not in_state:
            added.append(path)
        elif not in_local and in_state:
            removed.append(path)
        elif local_files[path] == state_files[path]:
            identical.append(path)
        else:
            modified.append(path)

    # Print summary
    total = len(all_paths)
    print(f"\nFiles: {total} total, {len(identical)} identical, "
          f"{len(modified)} modified, {len(added)} local-only, {len(removed)} remote-only")

    if not added and not removed and not modified:
        print("OK: In sync")
    else:
        if added:
            print(f"\nLocal-only (not yet pushed):")
            for p in added:
                print(f"  + {p}")

        if removed:
            print(f"\nRemote-only (not in src):")
            for p in removed:
                print(f"  - {p}")

        if modified:
            print(f"\nModified ({len(modified)} files):")
            for path in modified:
                print(f"  ~ {path}")
                if show_content:
                    _print_unified_diff(
                        state_files[path], local_files[path], path
                    )

    print(f"\n{'='*60}")

    return {
        "added": added,
        "removed": removed,
        "modified": modified,
        "identical": identical,
    }


def _print_unified_diff(remote_bytes: bytes, local_bytes: bytes, path: str):
    """Print a truncated unified diff between remote and local content."""
    try:
        remote_lines = remote_bytes.decode("utf-8").splitlines(keepends=True)
        local_lines = local_bytes.decode("utf-8").splitlines(keepends=True)
    except UnicodeDecodeError:
        print("      (binary content differs)")
        return

    diff_lines = list(difflib.unified_diff(
        remote_lines, local_lines,
        fromfile=f"remote:{path}",
        tofile=f"local:{path}",
        n=2,
    ))
    if not diff_lines:
        return

    max_lines = 30
    for line in diff_lines[:max_lines]:
        print(f"      {line.rstrip()}")
    if len(diff_lines) > max_lines:
        print(f"      ... ({len(diff_lines) - max_lines} more lines)")


# =============================================================================
# Status — overview of environments, drift, and patches
# =============================================================================

def status(config: ProjectConfig, env: str | None = None) -> None:
    """Print status overview for all or a specific environment.

    Shows last pull timestamps, file counts, and patch warnings.

    Args:
        config: Loaded project configuration.
        env: Optional specific environment. If None, shows all.
    """
    envs = [env] if env else config.env_names()
    scopes = list(config.scopes.keys())

    print(f"\n{'='*60}")
    print(f"  {config.name.upper()} Project Status")
    print(f"{'='*60}\n")

    # Summary table
    print(f"  {'Env':<8} {'Scope':<14} {'Last Pull':<14} {'Files':<10} {'Patches':<10}")
    print(f"  {'-'*8} {'-'*14} {'-'*14} {'-'*10} {'-'*10}")

    for e in envs:
        for scope in scopes:
            state = load_state(config.state_dir(e, scope))
            patches = _count_patches(config.patches_dir(e) / scope)

            if state:
                last_pull = format_age(state.get("last_pull", ""))
                file_count = len(state.get("files", []))
            else:
                last_pull = "never"
                file_count = 0

            print(f"  {e:<8} {scope:<14} {last_pull:<14} {file_count:<10} {patches:<10}")

    # Patch warnings
    print()
    max_age = config.patch_max_age_days
    now = datetime.now(timezone.utc)

    for e in envs:
        patches_base = config.patches_dir(e)
        if not patches_base.exists():
            continue

        old_patches = []
        for fp in patches_base.rglob("*"):
            if fp.is_dir() or fp.name.startswith("."):
                continue
            age_days = (now - datetime.fromtimestamp(fp.stat().st_mtime, tz=timezone.utc)).days
            if age_days >= max_age:
                rel = fp.relative_to(patches_base).as_posix()
                old_patches.append((rel, age_days))

        if old_patches:
            print(f"  WARN: patches/{e}/ has {len(old_patches)} aging patches "
                  f"(oldest: {max(d for _, d in old_patches)} days)")
            for path, age in sorted(old_patches):
                print(f"    - {path} ({age}d)")
            print(f"  Consider merging back to src/\n")

    print(f"{'='*60}")


def _count_patches(patches_dir: Path) -> int:
    """Count patch files in a directory."""
    if not patches_dir.exists():
        return 0
    return sum(1 for fp in patches_dir.rglob("*")
               if fp.is_file() and not fp.name.startswith("."))
