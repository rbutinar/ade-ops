#!/usr/bin/env python3
"""ade-ops CLI — main entry point.

Command groups:
    pull       Download remote state into state/{env}/{scope}/
    push       Assemble src + overlay + patches and upload to remote
    diff       Compare assembled local against pulled state
    status     Project overview (last pull, file counts, patches)
    preflight  Verify environment is ready to operate

Usage:
    python -m core.cli preflight
    python -m core.cli status --project distributions/reference/projects/databricks-fabric-migration
    python -m core.cli pull --project ... --env dev --scope notebooks
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import click

from ..connectors.databricks import DatabricksConnector
from ..connectors.fabric import FabricConnector
from ..connectors.fabric_warehouse import FabricWarehouseConnector
from ..engine.config import (
    ProjectConfig,
    load_credentials,
    load_project,
)
from ..engine.operations import diff as op_diff
from ..engine.operations import pull as op_pull
from ..engine.operations import push as op_push
from ..engine.operations import status as op_status
# Publish helpers are lab-side only — not present in consumer distributions
# (the publish engine is the framework maintainer's tool). Wrap import in
# try/except so the rest of the CLI keeps working when this file is mirrored
# into a downstream distribution that doesn't ship publish.py.
try:
    from ..engine.publish import (
        lab_head_short,
        publish as op_publish,
        publish_to_git,
        wipe_for_orphan,
    )
    _PUBLISH_AVAILABLE = True
except ImportError:
    _PUBLISH_AVAILABLE = False
    op_publish = None
    publish_to_git = None
    wipe_for_orphan = None
    def lab_head_short(_path):  # noqa: E306 — minimal fallback
        return ""


# =============================================================================
# Helpers
# =============================================================================

def _resolve_project_root(project_arg: str | None) -> Path:
    """Find the nearest project root.

    Searches ``project_arg`` (if given) or the current working directory and
    its ancestors for a ``config/project.yaml`` file.
    """
    start = Path(project_arg).resolve() if project_arg else Path.cwd()
    cur = start
    for _ in range(20):
        if (cur / "config" / "project.yaml").exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent

    raise click.ClickException(
        "No project.yaml found. Pass --project PATH or run from inside a project."
    )


def _load(project_arg: str | None) -> ProjectConfig:
    return load_project(_resolve_project_root(project_arg))


def _append_ops_log(
    config: ProjectConfig,
    op: str,
    env: str | None,
    scope: str | None,
    outcome: str,
    detail: str = "",
) -> None:
    """Append one audit line to ``{project_root}/ops.log``.

    Format matches the project's CLAUDE.md "Audit Trail" convention:
        ``{ISO} | {role} | {OP} | {env} | {scope}: {detail} | {ok|fail}``

    Creates the file if missing. Role is taken from ``ADEOPS_ROLE`` env var
    (set by ``/ops-dev``, ``/ops-prod``, ``/ops-review`` role sessions) and
    defaults to ``cli``. Best-effort: a logging failure must not break the
    operation itself.
    """
    role = os.environ.get("ADEOPS_ROLE", "cli")
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    line = (
        f"{timestamp} | {role} | {op} | {env or '-'} | "
        f"{scope or '-'}: {detail} | {outcome}\n"
    )
    try:
        with (config.root / "ops.log").open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def _build_connector(scope: str, config: ProjectConfig, env: str | None = None):
    """Build the connector for a scope, using the project's credentials.

    When ``env`` is passed and ``project.yaml`` declares
    ``environments.{env}.platforms.{connector}.auth``, the block is merged
    over the credentials so different envs can use different identities
    (e.g. dual-identity setups: native user for one platform, guest
    identity for another).
    """
    connector_name = config.connector_for_scope(scope)
    credentials = load_credentials(config.root)

    env_platform_auth = None
    if env:
        env_cfg = config.env_config(env)
        env_platform_auth = (
            env_cfg.get("platforms", {})
            .get(connector_name, {})
            .get("auth")
        )

    if connector_name == "databricks":
        db_host = config.platforms.get("databricks", {}).get("host", "")
        return DatabricksConnector.from_credentials(credentials, host=db_host)
    if connector_name == "fabric":
        return FabricConnector.from_credentials(
            credentials, env_platform_auth=env_platform_auth
        )
    if connector_name == "fabric_warehouse":
        return FabricWarehouseConnector.from_credentials(credentials)

    raise click.ClickException(
        f"Connector '{connector_name}' is not implemented. "
        f"Supported: databricks, fabric, fabric_warehouse."
    )


# =============================================================================
# Root group
# =============================================================================

@click.group()
@click.version_option(version="0.1.0", prog_name="ade-ops")
def cli():
    """ade-ops — Agentic Data Engineering Operations."""


# =============================================================================
# Operations
# =============================================================================

@cli.command()
@click.option("--project", "-p", default=None, help="Project root (default: nearest ancestor)")
@click.option("--env", "-e", required=True, help="Target environment")
@click.option("--scope", "-s", required=True, help="Asset scope (e.g. notebooks)")
@click.option("--filter", "-f", "filter_pattern", default=None,
              help="Optional pipeline/folder filter")
def pull(project, env, scope, filter_pattern):
    """Download remote state into state/{env}/{scope}/."""
    config = _load(project)
    connector = _build_connector(scope, config, env=env)
    try:
        op_pull(config, env, scope, connector, pipeline_filter=filter_pattern)
        _append_ops_log(config, "PULL", env, scope, "ok")
    except Exception:
        _append_ops_log(config, "PULL", env, scope, "fail")
        raise


@cli.command()
@click.option("--project", "-p", default=None)
@click.option("--env", "-e", required=True)
@click.option("--scope", "-s", required=True)
@click.option("--dry-run/--no-dry-run", default=False,
              help="Show what would be pushed without uploading")
@click.option("--filter", "-f", "filter_pattern", default=None)
def push(project, env, scope, dry_run, filter_pattern):
    """Assemble src + overlay + patches and upload to remote."""
    config = _load(project)
    connector = _build_connector(scope, config, env=env)
    op_label = "PUSH-DRY" if dry_run else "PUSH"
    try:
        result = op_push(config, env, scope, connector, dry_run=dry_run, file_filter=filter_pattern)
    except Exception:
        _append_ops_log(config, op_label, env, scope, "fail", detail="exception")
        raise
    # Granular outcome: ok / fail / partial / empty (see PushResult.outcome).
    # Detail field captures the count, so a log scan reveals partial failures
    # immediately (no need to read the operation transcript).
    detail = f"{result.pushed}/{result.total}"
    if result.failed_paths:
        detail += f" — failed: {len(result.failed_paths)}"
    _append_ops_log(config, op_label, env, scope, result.outcome, detail=detail)
    if result.outcome == "fail":
        sys.exit(1)


@cli.command()
@click.option("--project", "-p", default=None)
@click.option("--env", "-e", required=True)
@click.option("--scope", "-s", required=True)
@click.option("--no-content", is_flag=True, help="Suppress unified diff output")
@click.option("--filter", "-f", "filter_pattern", default=None)
def diff(project, env, scope, no_content, filter_pattern):
    """Compare assembled local against pulled remote state."""
    config = _load(project)
    try:
        op_diff(config, env, scope, show_content=not no_content, file_filter=filter_pattern)
        _append_ops_log(config, "DIFF", env, scope, "ok")
    except Exception:
        _append_ops_log(config, "DIFF", env, scope, "fail")
        raise


def _resolve_lab_root(lab_arg: str | None) -> Path:
    """Find the lab root — nearest ancestor with both ``core/`` and ``distributions/``."""
    start = Path(lab_arg).resolve() if lab_arg else Path.cwd()
    cur = start
    for _ in range(20):
        if (cur / "core").is_dir() and (cur / "distributions").is_dir():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    raise click.ClickException(
        "Lab root not found (looking for ancestor with both core/ and distributions/)."
    )


@cli.command()
@click.option("--distribution", "-d", required=True,
              help="Distribution slug to publish (e.g. reference)")
@click.option("--target-dir", "-t", required=True, type=click.Path(),
              help="Target directory for publish output (created if missing)")
@click.option("--dry-run/--no-dry-run", default=False,
              help="Compute the publish without writing any files")
@click.option("--lab-root", "-l", default=None,
              help="Lab repo root (default: nearest ancestor with core/ + distributions/)")
@click.option("--yes", "-y", is_flag=True,
              help="Skip the confirm-before-write prompt (use in CI)")
@click.option("--preserve-history/--no-preserve-history", default=False,
              help="Opt out from the orphan release model: do NOT wipe target "
                   "before write (incremental publish over existing .git). "
                   "Default is OFF — target is wiped to guarantee that the "
                   "public history reveals nothing about prior state.")
@click.option("--push", "push_remote", default=None,
              help="After write: git init + single commit + force-push to "
                   "this remote URL. Implicitly requires the orphan release "
                   "model (cannot combine with --preserve-history).")
@click.option("--branch", default="main",
              help="Target branch name when --push is used (default: main)")
@click.option("--publish-as-name", default=None,
              help="git user.name for the publish commit (default: use global config)")
@click.option("--publish-as-email", default=None,
              help="git user.email for the publish commit (default: use global "
                   "config). For public preview releases, pass a GitHub no-reply "
                   "address to keep maintainer email private.")
def publish(distribution, target_dir, dry_run, lab_root, yes,
            preserve_history, push_remote, branch,
            publish_as_name, publish_as_email):
    """Publish a distribution to a public target dir, sanitized and filtered.

    Walks the lab tree, drops lab-only paths, applies sanitization-patterns.md
    REPLACE rules in flight, refuses to write if any BLOCK pattern matches
    the post-replace text, and verifies ALLOW assertions on the target.

    \b
    Release model — orphan-by-default:
      The public preview is a release artefact, not a development workshop.
      By default the target dir is wiped before write and (with --push) the
      remote receives a single force-pushed commit. No prior history survives.
      Full provenance lives in the lab private repo. Use --preserve-history
      to opt out (incremental publish; not recommended for public targets).
    """
    if push_remote and preserve_history:
        click.echo(click.style(
            "ERROR: --push and --preserve-history are mutually exclusive. "
            "The orphan release model requires a fresh repo per publish.",
            fg="red", bold=True,
        ))
        sys.exit(2)

    if not _PUBLISH_AVAILABLE:
        click.echo(click.style(
            "ERROR: publish engine not available in this distribution. "
            "The /ops-publish skill is maintainer-side only — run it from the "
            "lab repo, not from a downstream distribution.",
            fg="red", bold=True,
        ))
        sys.exit(2)

    lab = _resolve_lab_root(lab_root)
    target = Path(target_dir).resolve()
    lab_rev = lab_head_short(lab)

    click.echo(click.style("\nade-ops publish", fg="cyan", bold=True))
    click.echo("=" * 60)
    click.echo(f"  lab root        : {lab}")
    click.echo(f"  lab HEAD        : {lab_rev or '(not a git repo)'}")
    click.echo(f"  distribution    : {distribution}")
    click.echo(f"  target dir      : {target}")
    click.echo(f"  mode            : {'DRY RUN' if dry_run else 'WRITE'}")
    click.echo(f"  release model   : "
               f"{'incremental (history preserved)' if preserve_history else 'orphan (target wiped, fresh history)'}")
    if push_remote:
        click.echo(f"  push to remote  : {push_remote} (branch {branch})")
    click.echo()

    # First pass — dry-run to surface violations even when caller asked for write
    pre = op_publish(lab, distribution, target, dry_run=True)

    click.echo(f"Files to publish : {pre.files_published}")
    click.echo(f"Replacements     : {len(pre.replacements)}")
    click.echo(f"BLOCK violations : {len(pre.block_violations)}")

    if pre.block_violations:
        click.echo()
        click.echo(click.style(
            "BLOCKED: cannot publish until the following are fixed in source",
            fg="red", bold=True,
        ))
        # Group by pattern for readable summary
        from collections import Counter
        by_pattern = Counter(v.pattern_name for v in pre.block_violations)
        for pat, n in by_pattern.most_common():
            click.echo(f"  [{pat}] {n} match(es)")
        # First few concrete examples
        click.echo()
        click.echo("Sample (first 10):")
        for v in pre.block_violations[:10]:
            click.echo(f"  {v}")
        if len(pre.block_violations) > 10:
            click.echo(f"  ... and {len(pre.block_violations) - 10} more")
        sys.exit(1)

    if pre.replacements:
        click.echo()
        click.echo(click.style("Replacements (auto-substituted):", fg="yellow"))
        from collections import defaultdict
        by_file_pat: dict[tuple[str, str], int] = defaultdict(int)
        for r in pre.replacements:
            by_file_pat[(r.file, r.pattern_name)] += r.count
        for (f, p), count in sorted(by_file_pat.items())[:20]:
            click.echo(f"  {f}  [{p}]  x{count}")
        if len(by_file_pat) > 20:
            click.echo(f"  ... and {len(by_file_pat) - 20} more")

    if dry_run:
        click.echo()
        click.echo(click.style("DRY RUN complete — no files written.", fg="green"))
        return

    # Confirm before write
    if not yes:
        click.echo()
        action = "wipe + write" if not preserve_history else "write (preserve)"
        push_msg = f" + force-push to {push_remote}" if push_remote else ""
        click.echo(click.style(
            f"About to {action} {pre.files_published} files to {target}{push_msg}",
            fg="yellow", bold=True,
        ))
        if not click.confirm("Proceed?", default=False):
            click.echo("Aborted.")
            sys.exit(0)

    # Orphan release model: wipe target before write. Skipped when the
    # caller explicitly opted into --preserve-history.
    if not preserve_history:
        click.echo()
        click.echo("Wiping target dir (orphan release model)...")
        removed = wipe_for_orphan(target)
        click.echo(f"  removed {removed} top-level entries")

    # Actual write
    click.echo()
    click.echo("Writing publish target...")
    report = op_publish(lab, distribution, target, dry_run=False)

    click.echo()
    if report.allow_misses:
        click.echo(click.style(
            "WARNING: ALLOW assertions missing on target",
            fg="red", bold=True,
        ))
        for name in report.allow_misses:
            click.echo(f"  [missing] {name}")
        click.echo("The publish wrote files, but positive assertions failed.")
        click.echo("Fix the target (e.g. add LICENSE) and re-run.")
        sys.exit(1)

    click.echo(click.style(
        f"Published {report.files_published} files to {target}",
        fg="green", bold=True,
    ))

    # Git publish step (opt-in via --push)
    if push_remote:
        click.echo()
        click.echo(click.style(
            f"Pushing as orphan release to {push_remote} (branch {branch})...",
            fg="cyan", bold=True,
        ))
        git_result = publish_to_git(
            target,
            remote=push_remote,
            branch=branch,
            lab_rev=lab_rev,
            author_name=publish_as_name,
            author_email=publish_as_email,
        )
        click.echo(f"  commit  : {git_result.commit_sha[:12]}")
        click.echo(f"  message : {git_result.commit_message}")
        click.echo(click.style(
            f"Force-pushed to {push_remote} ({branch})",
            fg="green", bold=True,
        ))


@cli.command()
@click.option("--project", "-p", default=None)
@click.option("--env", "-e", default=None, help="Specific env (default: all)")
def status(project, env):
    """Project status overview."""
    config = _load(project)
    try:
        op_status(config, env=env)
        _append_ops_log(config, "STATUS", env, None, "ok")
    except Exception:
        _append_ops_log(config, "STATUS", env, None, "fail")
        raise


# =============================================================================
# Seat probe — consolidated snapshot for /seat + /ops-local-manager boot
# =============================================================================

@cli.command(name="seat-probe")
@click.option("--branch", "-b", default=None,
              help="Remote branch to compare HEAD against (auto-detect if omitted)")
def seat_probe(branch):
    """Emit a JSON snapshot of seat state for /seat and /ops-local-manager.

    Implemented as a Python CLI command so the tool-call display shows
    one short line (`python -m core.cli seat-probe`) instead of a
    verbose PowerShell hashtable. JSON output is collapsed by default
    in the UI; the consuming skill builds the user-facing recap card.
    """
    import json
    import subprocess
    from pathlib import Path

    def _git(*args: str, default: str = "") -> str:
        try:
            result = subprocess.run(
                ["git", *args],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", check=False,
            )
            return result.stdout.strip() if result.returncode == 0 else default
        except Exception:
            return default

    def _venv_active() -> bool:
        try:
            result = subprocess.run(
                ["python", "-c", "import sys; print(int(sys.prefix != sys.base_prefix))"],
                capture_output=True, text=True, check=False,
            )
            return result.stdout.strip() == "1"
        except Exception:
            return False

    # Auto-detect remote branch if not specified
    if not branch:
        # Try to read upstream tracking of current branch
        upstream = _git("rev-parse", "--abbrev-ref", "@{upstream}", default="origin/main")
        branch = upstream

    _git("fetch", "origin", "--quiet")

    cwd = Path.cwd()

    # Find seat manifest (new-style or legacy)
    seat_yaml = next(cwd.glob("distributions/*/.seat.yaml"), None)
    clone_identity = cwd / ".claude/clone-identity.yaml"
    manifest_path = (
        str(seat_yaml.relative_to(cwd).as_posix()) if seat_yaml
        else (".claude/clone-identity.yaml" if clone_identity.exists() else None)
    )

    # Find latest session log if any
    last_session = None
    for sess_dir in cwd.glob("distributions/*/.seat-sessions"):
        if sess_dir.is_dir():
            sessions = sorted(sess_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
            if sessions:
                last_session = sessions[0].name
                break

    # Find credentials files (any project under any distribution)
    creds_exists = any(cwd.glob("distributions/*/projects/*/config/credentials.yaml"))

    snapshot = {
        "user": _git("config", "user.name") or "",
        "email": _git("config", "user.email") or "",
        "head": _git("rev-parse", "--short", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "head_subject": _git("log", "-1", "--format=%s"),
        "head_age": _git("log", "-1", "--format=%cr"),
        "behind": int(_git("rev-list", "--count", f"HEAD..{branch}", default="0") or 0),
        "ahead": int(_git("rev-list", "--count", f"{branch}..HEAD", default="0") or 0),
        "dirty_count": len(_git("status", "--porcelain").splitlines()) if _git("status", "--porcelain") else 0,
        "venv_active": _venv_active(),
        "mcp_exists": (cwd / ".mcp.json").exists(),
        "creds_exists": creds_exists,
        "seat_manifest": manifest_path,
        "last_session": last_session,
        "maintainer_notes": next(
            (str(p.relative_to(cwd).as_posix())
             for p in cwd.glob("distributions/*/.maintainer-notes.md") if p.exists()),
            None
        ),
        "origin_url": _git("remote", "get-url", "origin"),
    }
    click.echo(json.dumps(snapshot, indent=2))


# =============================================================================
# PBIR — Build + Deploy a Power BI Report from a YAML spec
# =============================================================================

@cli.command(name="pbir-create")
@click.argument("name")
@click.option("--project", "-p", default=None,
              help="Project root (default: nearest ancestor)")
@click.option("--env", "-e", required=True,
              help="Target environment (resolves Fabric workspace from overlay)")
@click.option("--spec", "-s", required=True, type=click.Path(exists=True),
              help="YAML spec file describing pages + visuals")
@click.option("--model-id", default=None,
              help="Power BI semantic model GUID (preferred). Overrides spec value if both set.")
@click.option("--workspace-display-name", default=None,
              help="Workspace display name override for the connection string")
@click.option("--initial-catalog", default=None,
              help="Initial catalog override for the connection string")
@click.option("--output-dir", "-o", default=None, type=click.Path(),
              help="Directory where the .Report folder is written (default: ./local/build/<name>)")
@click.option("--no-deploy", is_flag=True,
              help="Build to disk only — do not deploy to Fabric workspace")
@click.option("--yes", "-y", is_flag=True,
              help="Skip the confirm-before-deploy prompt")
def pbir_create(name, project, env, spec, model_id, workspace_display_name,
                initial_catalog, output_dir, no_deploy, yes):
    """Build a new PBIR report from a YAML spec and deploy to a Fabric workspace.

    Wraps the engine ``ReportBuilder.from_spec()`` + deploy lifecycle so the
    operator does not have to hand-write the build script. The spec format
    is documented in ``.claude/commands/pbir-create.md``.

    Closes P1-B from the ade-ops-2 release-readiness assessment.
    """
    import base64
    from core.platforms.powerbi.pbir_engine import ReportBuilder

    config = _load(project)
    op_label = "PBIR-CREATE"

    spec_path = Path(spec).resolve()
    output_dir_path = (
        Path(output_dir).resolve() if output_dir
        else config.root / "local" / "build" / name
    )
    output_dir_path.mkdir(parents=True, exist_ok=True)

    click.echo(click.style(f"\nade-ops pbir-create — {name}", fg="cyan", bold=True))
    click.echo("=" * 60)
    click.echo(f"  spec        : {spec_path}")
    click.echo(f"  env         : {env}")
    click.echo(f"  output dir  : {output_dir_path}")
    click.echo(f"  deploy      : {'NO (--no-deploy)' if no_deploy else 'YES'}")

    # Build
    try:
        report = ReportBuilder.from_spec(
            spec_path,
            model_id=model_id,
            workspace_display_name=workspace_display_name,
            initial_catalog=initial_catalog,
        )
        report_dir = report.save(output_dir_path)
        click.echo(click.style(
            f"\nBuilt report at {report_dir}",
            fg="green", bold=True,
        ))
    except Exception as exc:
        click.echo(click.style(f"\nBuild failed: {exc}", fg="red", bold=True))
        _append_ops_log(config, op_label, env, None, "fail",
                        detail=f"build: {type(exc).__name__}")
        raise

    if no_deploy:
        _append_ops_log(config, op_label, env, None, "ok", detail="build-only")
        return

    # Deploy
    env_cfg = config.env_config(env)
    workspace_id = (
        env_cfg.get("overlays", {}).get("power_bi", {}).get("report_workspace_id")
        or env_cfg.get("platforms", {}).get("fabric", {}).get("workspace_id")
    )
    if not workspace_id:
        click.echo(click.style(
            f"\nNo target workspace resolved for env {env}. Set "
            f"overlays.power_bi.report_workspace_id or "
            f"platforms.fabric.workspace_id.",
            fg="red", bold=True,
        ))
        _append_ops_log(config, op_label, env, None, "fail",
                        detail="no-workspace")
        raise click.ClickException("workspace id not configured")

    if not yes:
        click.echo()
        click.echo(click.style(
            f"About to deploy {name} to Fabric workspace {workspace_id}",
            fg="yellow", bold=True,
        ))
        if not click.confirm("Proceed?", default=False):
            click.echo("Aborted (build is on disk, no deploy).")
            sys.exit(0)

    connector = _build_connector("power_bi", config, env=env)
    parts = []
    for file_path in report_dir.rglob("*"):
        if file_path.is_dir():
            continue
        rel = file_path.relative_to(report_dir).as_posix()
        parts.append({
            "path": rel,
            "payload": base64.b64encode(file_path.read_bytes()).decode("ascii"),
            "payloadType": "InlineBase64",
        })
    definition = {"parts": parts}

    existing = connector.client.find_item_by_name(workspace_id, "Report", name)
    try:
        if existing:
            connector.client.update_item_definition(
                workspace_id, existing["id"], definition
            )
            action = "update"
            item_id = existing["id"]
        else:
            result = connector.client.create_item(
                workspace_id,
                display_name=name,
                item_type="Report",
                definition=definition,
            )
            action = "create"
            item_id = result.get("id", "<unknown>")
        click.echo(click.style(
            f"Deployed ({action}) — item id: {item_id}",
            fg="green", bold=True,
        ))
        _append_ops_log(config, op_label, env, None, "ok",
                        detail=f"{action} {name} ws={workspace_id} parts={len(parts)}")
    except Exception as exc:
        click.echo(click.style(f"\nDeploy failed: {exc}", fg="red", bold=True))
        _append_ops_log(config, op_label, env, None, "fail",
                        detail=f"deploy: {type(exc).__name__}")
        raise


# =============================================================================
# Preflight
# =============================================================================

@cli.command()
@click.option("--project", "-p", default=None)
@click.option("--env", "-e", default=None,
              help="If set, also test connectivity for this env")
@click.option("--scope", "-s", default=None,
              help="Scope to test. If omitted, all configured scopes are tested.")
def preflight(project, env, scope):
    """Verify environment is ready: Python, deps, credentials, connectivity.

    Without --scope, every scope declared in project.yaml is checked so the
    user sees the full Databricks + Fabric (or whatever platforms are wired)
    picture in a single invocation. Pass --scope X to narrow to one connector.
    """
    click.echo()
    click.echo(click.style("ade-ops preflight check", fg="cyan", bold=True))
    click.echo("=" * 60)

    failures = 0

    # 1. Python
    py = sys.version_info
    py_ok = py >= (3, 10)
    _check("Python >= 3.10", py_ok, f"got {py.major}.{py.minor}.{py.micro}")
    if not py_ok:
        failures += 1

    # 2. Dependencies
    for mod, label in [("yaml", "pyyaml"), ("httpx", "httpx"), ("click", "click")]:
        try:
            __import__(mod)
            _check(f"dep: {label}", True, "installed")
        except ImportError:
            _check(f"dep: {label}", False, "MISSING — pip install -r requirements.txt")
            failures += 1

    # 3. Project config
    try:
        root = _resolve_project_root(project)
        config = load_project(root)
        _check("project config", True, f"{config.client}/{config.name} at {root}")
    except Exception as e:
        _check("project config", False, str(e))
        _summary(failures + 1)
        return

    # 4. credentials.yaml
    creds_path = config.root / "config" / "credentials.yaml"
    creds_ok = creds_path.exists()
    detail = (
        str(creds_path.relative_to(config.root))
        if creds_ok
        else "missing — copy credentials.example.yaml → credentials.yaml"
    )
    _check("credentials.yaml", creds_ok, detail)
    if not creds_ok:
        failures += 1

    # 5. Load credentials once; per-scope checks below decide which fields matter.
    creds = None
    if creds_ok:
        try:
            creds = load_credentials(config.root)
        except Exception as e:
            _check("credentials load", False, str(e))
            failures += 1

    # 6. Per-scope checks: credentials-for-connector + connectivity.
    # When --scope is omitted we iterate over every configured scope so the
    # user sees the full picture in one invocation. A failure in one scope's
    # creds block skips ONLY that scope's connectivity probe, not the others.
    if creds is not None:
        scopes_to_check = [scope] if scope else list(config.scopes.keys())
        for sc in scopes_to_check:
            connector_name = config.connector_for_scope(sc)
            click.echo()
            click.echo(click.style(
                f"  -- scope: {sc} ({connector_name}) --", fg="yellow"
            ))
            scope_creds_failures = _preflight_scope_credentials(creds, connector_name)
            failures += scope_creds_failures
            if env and scope_creds_failures == 0:
                if connector_name == "databricks":
                    failures += _preflight_databricks(config, env, sc)
                elif connector_name == "fabric":
                    failures += _preflight_fabric(config, env, sc)
                else:
                    _check(
                        f"connectivity [{env}/{sc}]",
                        True,
                        f"skipped — no probe implemented for connector '{connector_name}'",
                    )

    _summary(failures)


def _preflight_scope_credentials(creds: dict, connector_name: str) -> int:
    """Check the credentials a given connector needs. Returns failure count."""
    failures = 0
    if connector_name == "databricks":
        token = creds.get("databricks", {}).get("token", "")
        tok_ok = (
            isinstance(token, str)
            and len(token) > 10
            and "${" not in token
        )
        _check(
            "databricks token resolved",
            tok_ok,
            "set" if tok_ok else "missing or unresolved — set DATABRICKS_TOKEN env var",
        )
        if not tok_ok:
            failures += 1
    elif connector_name == "fabric":
        import shutil
        az_path = shutil.which("az")
        az_ok = az_path is not None
        _check(
            "az CLI available",
            az_ok,
            az_path if az_ok else "missing — install Azure CLI for Fabric auth",
        )
        if not az_ok:
            failures += 1
        # The fabric connector documents distinct keys per auth_method
        # (see core/connectors/fabric.py docstring): az_cli uses
        # ``az_tenant_id``, service_principal uses ``tenant_id`` +
        # ``client_id`` + ``client_secret``, device_code uses ``tenant_id``.
        # Check the right keys for the active auth_method.
        fabric_cfg = creds.get("fabric", {})
        auth_method = fabric_cfg.get("auth_method", "az_cli")

        def _resolved(value) -> bool:
            return isinstance(value, str) and bool(value) and "${" not in value

        if auth_method == "az_cli":
            tenant = fabric_cfg.get("az_tenant_id", "")
            ok = _resolved(tenant)
            _check(
                "fabric az_tenant_id resolved",
                ok,
                "set" if ok else "missing or unresolved — set FABRIC_TENANT_ID env var or fill az_tenant_id literally",
            )
            if not ok:
                failures += 1
        elif auth_method == "service_principal":
            for key, hint in (
                ("tenant_id", "FABRIC_TENANT_ID"),
                ("client_id", "FABRIC_CLIENT_ID"),
                ("client_secret", "FABRIC_CLIENT_SECRET"),
            ):
                ok = _resolved(fabric_cfg.get(key, ""))
                _check(
                    f"fabric {key} resolved",
                    ok,
                    "set" if ok else f"missing or unresolved — set {hint} env var or fill {key} literally",
                )
                if not ok:
                    failures += 1
        elif auth_method == "device_code":
            tenant = fabric_cfg.get("tenant_id", "")
            ok = _resolved(tenant)
            _check(
                "fabric tenant_id resolved",
                ok,
                "set" if ok else "missing or unresolved — set FABRIC_TENANT_ID env var",
            )
            if not ok:
                failures += 1
        else:
            _check(
                f"fabric auth_method '{auth_method}'",
                False,
                "unknown — supported: az_cli, service_principal, device_code",
            )
            failures += 1
    else:
        _check(
            f"credentials [{connector_name}]",
            True,
            f"no preflight check implemented for connector '{connector_name}'",
        )
    return failures


def _preflight_databricks(config: ProjectConfig, env: str, scope: str) -> int:
    try:
        env_cfg = config.env_config(env)
        ws_path = (
            env_cfg.get("platforms", {})
            .get("databricks", {})
            .get("workspace_path", "")
        )
        if not ws_path:
            _check(f"workspace_path[{env}]", False, "not configured")
            return 1
        if "${" in ws_path:
            unresolved = ws_path[ws_path.find("${") + 2 : ws_path.find("}")]
            _check(
                f"workspace_path[{env}]",
                False,
                f"unresolved env var '{unresolved}' — set it in your environment",
            )
            return 1
        connector = _build_connector(scope, config, env=env)
        objs = connector.client.list_workspace(ws_path)
        _check(
            f"databricks reachable [{env}]",
            True,
            f"{len(objs)} top-level objects under {ws_path}",
        )
        return 0
    except Exception as e:
        _check(f"databricks reachable [{env}]", False, f"{type(e).__name__}: {e}")
        return 1


def _preflight_fabric(config: ProjectConfig, env: str, scope: str) -> int:
    """Probe Fabric identity by fetching the configured workspace.

    A 404 here is the classic 404-vs-403 trap: list-read works but the
    caller cannot read this specific workspace at definition level —
    usually because the identity lacks Power BI Pro. See
    core/docs/fabric_404_vs_403.md.
    """
    import httpx
    try:
        env_cfg = config.env_config(env)
        ws_id = (
            env_cfg.get("platforms", {})
            .get("fabric", {})
            .get("workspace_id", "")
        )
        if not ws_id:
            _check(f"fabric workspace_id[{env}]", False, "not configured")
            return 1
        if "${" in ws_id:
            unresolved = ws_id[ws_id.find("${") + 2 : ws_id.find("}")]
            _check(
                f"fabric workspace_id[{env}]",
                False,
                f"unresolved env var '{unresolved}' — set it in your environment",
            )
            return 1
        connector = _build_connector(scope, config, env=env)
        ws = connector.client.get_workspace(ws_id)
        display = ws.get("displayName") or ws_id
        _check(
            f"fabric reachable [{env}]",
            True,
            f"identity OK for workspace '{display}'",
        )
        return 0
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        if status == 404:
            _check(
                f"fabric identity [{env}]",
                False,
                f"workspace returned 404 — likely missing PBI Pro on caller identity. "
                f"Verify with `az account show`; ensure AZURE_CONFIG_DIR points to the "
                f"profile with Power BI Pro (env-level override goes in project.yaml: "
                f"environments.{env}.platforms.fabric.auth.azure_config_dir).",
            )
        else:
            _check(f"fabric reachable [{env}]", False, f"HTTP {status}")
        return 1
    except Exception as e:
        _check(f"fabric reachable [{env}]", False, f"{type(e).__name__}: {e}")
        return 1


def _check(label: str, ok: bool, detail: str) -> None:
    mark = click.style("[OK]  ", fg="green") if ok else click.style("[FAIL]", fg="red")
    click.echo(f"  {mark} {label:32} {detail}")


def _summary(failures: int) -> None:
    click.echo()
    if failures == 0:
        click.echo(click.style("PREFLIGHT OK — ready to operate.", fg="green", bold=True))
    else:
        click.echo(click.style(f"PREFLIGHT FAILED — {failures} issue(s).", fg="red", bold=True))
        sys.exit(1)


# =============================================================================
# Entry
# =============================================================================

def main() -> None:
    cli()


if __name__ == "__main__":
    main()
