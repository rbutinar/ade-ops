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
import subprocess
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
    load_overlay,
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


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Run a git subcommand in ``cwd``, capturing output. Best-effort, never raises.

    Returns a CompletedProcess with returncode 1 + empty stdout if git is absent
    or the call errors, so callers branch on returncode without try/except. Kept as
    a module-level seam so the freshness preflight is unit-testable by monkeypatching.
    """
    try:
        return subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="")


def _git_head_sha(root: Path) -> str | None:
    """Short HEAD SHA of the repo containing the project, or None when not a repo."""
    r = _git(["rev-parse", "--short", "HEAD"], root)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def _preflight_git_freshness(config: ProjectConfig, *, ack_stale: bool) -> None:
    """Abort a power_bi push when the local tree is behind its upstream branch.

    A power_bi update is a wholesale ``updateDefinition`` — pushing from a stale
    tree silently drops whatever landed remote after the local HEAD (incident
    2026-05-28: 4 measures dropped). This fetches and compares ``HEAD..@{upstream}``;
    if behind and not acknowledged, it aborts with a recovery hint. Best-effort:
    a non-git checkout or a missing upstream skips the check (the engine ships in
    distributions that may run outside a git working tree).
    """
    root = config.root
    inside = _git(["rev-parse", "--is-inside-work-tree"], root)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return  # not a git checkout — the guard does not apply
    up = _git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"], root)
    if up.returncode != 0 or not up.stdout.strip():
        click.echo("  [preflight] no upstream tracking branch — git-freshness check skipped")
        return
    upstream = up.stdout.strip()
    fetched = _git(["fetch", "--quiet"], root)
    if fetched.returncode != 0:
        click.echo(
            f"  [preflight] git fetch failed — freshness is best-effort against "
            f"last-known {upstream}"
        )
    behind = _git(["rev-list", "--count", f"HEAD..{upstream}"], root)
    n = behind.stdout.strip()
    if not (behind.returncode == 0 and n.isdigit() and int(n) > 0):
        return  # up to date (or undeterminable) — proceed
    if not ack_stale:
        raise click.ClickException(
            f"local HEAD is {n} commit(s) behind {upstream}.\n"
            f"        A power_bi push is a wholesale updateDefinition — it would "
            f"overwrite the\n"
            f"        remote model with a stale payload and can silently drop prior "
            f"deploys.\n"
            f"        Recovery: git pull --ff-only (or git pull --rebase), then re-run.\n"
            f"        Bypass:   --ack-stale-remote (only if you understand the risk)."
        )
    click.echo(
        f"  [preflight] OVERRIDE: {n} commit(s) behind {upstream}, proceeding "
        f"(--ack-stale-remote)"
    )


# Production-like environments where a binding that silently resolves to a lower
# env (or is unresolved) is the "silent-success" deploy hazard: a `push --env prod`
# that targets cert because the prod overlay/patch companion was missing or stale
# (feedback 2026-06-05_push-prod-missing-patch-silent-env-cert, TICK-027).
_PROD_ENVS = frozenset({"prod"})


def _databricks_binding(config: ProjectConfig, env: str) -> dict[str, str]:
    """Resolve the effective databricks env binding (catalog/schema/workspace_path).

    Merges overlays/{env}.yaml ``databricks`` over project.yaml
    ``environments.{env}.platforms.databricks`` (overlay wins, mirroring the
    assembly pipeline). Values keep any unresolved ``${VAR}`` literal so the
    caller can flag it. Returns only the keys actually present.
    """
    env_cfg = config.env_config(env)
    plat = env_cfg.get("platforms", {}).get("databricks", {})
    try:
        ov = load_overlay(config.root, env).get("databricks", {})
    except FileNotFoundError:
        ov = {}
    merged = {**plat, **ov}
    return {k: merged[k] for k in ("catalog", "schema", "workspace_path")
            if merged.get(k)}


def _preflight_env_binding(
    config: ProjectConfig, env: str, scope: str, *, ack: bool, dry_run: bool
) -> None:
    """Surface the effective env binding + guard a prod push from a silent fallback.

    The silent-success guard for the databricks deploy target (TICK-027 ACT-002):

    - ALWAYS print the resolved catalog/schema/workspace_path, so the operator
      sees WHERE a push lands before trusting a green status.
    - ABORT if any binding value is unresolved (``${VAR}`` still literal) — the
      push would target a placeholder.
    - For a production-like env, ABORT if the resolved (catalog, workspace_path)
      EQUALS a lower env's binding — the "prod silently == cert" fallback — unless
      ``--ack-env-binding``.

    Databricks-only for now (the reported case); other connectors skip. On a
    dry-run the problems are surfaced but not raised, so the dry-run stays usable
    to inspect a broken binding.

    NOTE: this guards the OVERLAY/project-config binding the engine controls. It
    does NOT inspect a catalog hard-coded inside notebook content (which a
    ``patches/{env}/`` companion would override) — that divergence still needs
    the operator's post-run ``current_catalog()`` assertion.
    """
    if config.connector_for_scope(scope) != "databricks":
        return
    binding = _databricks_binding(config, env)
    if not binding:
        return  # nothing declared — _preflight_databricks covers "not configured"

    shown = " ".join(f"{k}={v}" for k, v in binding.items())
    click.echo(f"  [binding] effective {env} databricks target: {shown}")

    def _fail(msg: str) -> None:
        if dry_run:
            click.echo(click.style(f"  [binding] WOULD ABORT: {msg}", fg="yellow"))
        else:
            raise click.ClickException(msg)

    unresolved = [k for k, v in binding.items() if "${" in str(v)]
    if unresolved:
        _fail(
            f"{env} databricks binding has unresolved variable(s): "
            f"{', '.join(unresolved)}. The push would target a literal placeholder — "
            f"set the variable(s) or author the {env} overlay/patch binding."
        )
        return

    if env not in _PROD_ENVS:
        return

    target = (binding.get("catalog"), binding.get("workspace_path"))
    if not any(target):
        return
    for other in config.env_names():
        if other == env or other in _PROD_ENVS:
            continue
        ob = _databricks_binding(config, other)
        if (ob.get("catalog"), ob.get("workspace_path")) == target:
            if ack:
                click.echo(
                    f"  [binding] OVERRIDE: {env} binding equals '{other}' "
                    f"(--ack-env-binding)"
                )
                return
            _fail(
                f"{env} databricks binding is IDENTICAL to '{other}' "
                f"(catalog={target[0]} workspace_path={target[1]}).\n"
                f"        A '{env}' push would deploy to the '{other}' target — the "
                f"silent prod->lower-env fallback.\n"
                f"        Author the {env} overlay/patch with genuinely-{env} values, "
                f"or re-pull the {env} binding.\n"
                f"        Bypass: --ack-env-binding (only if {env} truly shares "
                f"'{other}' catalog + workspace)."
            )
            return


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


def _harness_version() -> str:
    """Read the harness version from the ``core/VERSION`` manifest."""
    try:
        return (
            (Path(__file__).resolve().parent.parent / "VERSION")
            .read_text(encoding="utf-8")
            .strip()
        )
    except OSError:
        return "0.0.0"


@click.group()
@click.version_option(version=_harness_version(), prog_name="ade-ops")
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
@click.option("--ack-stale-remote", is_flag=True, default=False,
              help="Proceed with a power_bi push even if the local tree is behind upstream")
@click.option("--ack-env-binding", is_flag=True, default=False,
              help="Proceed even if the prod binding equals a lower env's "
                   "(overrides the silent prod->cert fallback guard)")
def push(project, env, scope, dry_run, filter_pattern, ack_stale_remote, ack_env_binding):
    """Assemble src + overlay + patches and upload to remote."""
    config = _load(project)
    # Freshness preflight for the wholesale-replace scope: a power_bi update
    # pushed from a stale tree silently drops prior deploys (incident 2026-05-28).
    # Notebook pushes are guarded separately (post-import modified_at check).
    if scope == "power_bi" and not dry_run:
        _preflight_git_freshness(config, ack_stale=ack_stale_remote)
    # Binding guard: surface the effective target + abort a prod push that would
    # silently land on a lower env (missing/stale prod overlay or unresolved var).
    _preflight_env_binding(config, env, scope, ack=ack_env_binding, dry_run=dry_run)
    connector = _build_connector(scope, config, env=env)
    op_label = "PUSH-DRY" if dry_run else "PUSH"
    try:
        result = op_push(config, env, scope, connector, dry_run=dry_run, file_filter=filter_pattern)
    except Exception:
        _append_ops_log(config, op_label, env, scope, "fail", detail="exception")
        raise
    # Granular outcome: ok / fail / partial / empty (see PushResult.outcome).
    # Detail field captures the count, so a log scan reveals partial failures
    # immediately (no need to read the operation transcript). The HEAD SHA makes
    # stale-tree incidents reconstructable from the audit trail alone.
    detail = f"{result.pushed}/{result.total}"
    if result.failed_paths:
        detail += f" — failed: {len(result.failed_paths)}"
    head_sha = _git_head_sha(config.root)
    if head_sha:
        detail += f" @{head_sha}"
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

    def _open_branches(trunk: str, limit: int = 10) -> list[dict]:
        """Remote branches whose tip is NOT merged into ``trunk``.

        Surfaces un-merged work the seat would otherwise never see: ``seat-probe``
        compares HEAD against a single upstream, so sibling feature branches
        (e.g. ``feature/cr-...`` on a trunk-based distribution) are invisible.

        This is candidate detection, intentionally dumb: it cannot tell a
        live-divergent branch from a stale duplicate whose commits were already
        cherry-picked onto trunk (both are ``--no-merged``), and on a
        distribution with disconnected-root branches it will also list those.
        The consuming skill applies judgement; the PM layer is the precision
        filter (join to open CRs). Sorted most-recent-first, bounded.
        """
        raw = _git("branch", "-r", "--no-merged", trunk)
        if not raw:
            return []
        out: list[dict] = []
        for line in raw.splitlines():
            name = line.strip()
            if not name or "->" in name or name == trunk:
                continue
            short = name[len("origin/"):] if name.startswith("origin/") else name
            out.append({
                "name": short,
                "ahead": int(_git("rev-list", "--count", f"{trunk}..{name}", default="0") or 0),
                "age": _git("log", "-1", "--format=%cr", name),
                "_ct": int(_git("log", "-1", "--format=%ct", name, default="0") or 0),
            })
        out.sort(key=lambda b: b["_ct"], reverse=True)
        for b in out:
            del b["_ct"]
        return out[:limit]

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
        "open_branches": _open_branches(branch),
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
# Decks — PPTX generation from brand template + spec YAML
# =============================================================================
#
# See core/conventions/deck-template.md for the convention these commands
# implement (template storage in OneDrive, per-seat config/decks.yaml,
# real-layout discovery, spec schema).

@cli.command(name="deck-list")
def deck_list():
    """List declared template packs and the ``.pptx`` files in each."""
    from ..engine.decks import DecksConfigError, load_decks_config

    try:
        config = load_decks_config()
    except DecksConfigError as exc:
        click.echo(click.style(f"ERROR: {exc}", fg="red", bold=True))
        sys.exit(2)

    click.echo()
    click.echo(click.style("Deck template packs", fg="cyan", bold=True))
    click.echo("=" * 60)
    click.echo(f"  config       : {config.config_path}")
    click.echo(f"  default_pack : {config.default_pack or '(none)'}")
    click.echo(f"  output_dir   : {config.output_dir or '(spec dir)'}")
    click.echo()

    if not config.template_paths:
        click.echo("  (no template_paths declared in decks.yaml)")
        return

    for pack_name, pack_path in sorted(config.template_paths.items()):
        marker = " *" if pack_name == config.default_pack else "  "
        click.echo(f"{marker} {pack_name}")
        click.echo(f"    {pack_path}")
        if not pack_path.exists():
            click.echo(click.style(
                "    (folder does not exist — check OneDrive sync)", fg="yellow"
            ))
            continue
        pptx_files = sorted(pack_path.glob("*.pptx"))
        if not pptx_files:
            click.echo("    (no .pptx files)")
            continue
        for p in pptx_files:
            click.echo(f"      - {p.name}")


@cli.command(name="deck-catalog")
@click.argument("template", type=click.Path(exists=True, dir_okay=False))
def deck_catalog(template):
    """List a template's real layouts + placeholders (idx, name, type).

    This is the discovery step for authoring a spec: a slide picks a layout
    by ``index`` (or real name) and fills placeholders by ``idx``. No
    layout renaming is needed.
    """
    from ..engine.decks import catalog_template

    template_path = Path(template).resolve()
    catalog = catalog_template(template_path)

    click.echo()
    click.echo(click.style(f"Catalog: {template_path.name}", fg="cyan", bold=True))
    click.echo("=" * 60)
    click.echo(f"  template : {template_path}")
    click.echo(f"  layouts  : {len(catalog)}")
    click.echo()
    for info in catalog:
        click.echo(click.style(f"  [{info.index}] {info.name}", fg="cyan", bold=True))
        if not info.placeholders:
            click.echo("        (no placeholders)")
        for ph in info.placeholders:
            name = ph.name or "(unnamed)"
            click.echo(f"        idx={ph.idx:<3} {ph.type:<12} {name}")
    click.echo()


@cli.command(name="deck-validate")
@click.argument("spec", type=click.Path(exists=True, dir_okay=False))
def deck_validate(spec):
    """Check a spec's layout + placeholder references resolve against its template.

    Resolves the template from the spec's ``meta.pack`` / ``meta.template``
    (per-seat config/decks.yaml), then verifies every ``layout`` (index or
    name) and every placeholder ``idx`` the spec references exists. Run
    ``deck-catalog`` to see what a template exposes.
    """
    from ..engine.decks import BuildError, DecksConfigError, validate_spec

    spec_path = Path(spec).resolve()

    click.echo()
    click.echo(click.style(f"Validate spec: {spec_path.name}", fg="cyan", bold=True))
    click.echo("=" * 60)

    try:
        result = validate_spec(spec_path)
    except (BuildError, DecksConfigError) as exc:
        click.echo(click.style(f"ERROR: {exc}", fg="red", bold=True))
        sys.exit(2)

    click.echo(f"  spec     : {result.spec_path}")
    click.echo(f"  template : {result.template_path}")
    click.echo(f"  slides   : {result.slide_count}")
    click.echo()

    if result.ok:
        click.echo(click.style(result.summary(), fg="green", bold=True))
        return
    for issue in result.issues:
        click.echo(click.style(f"  - {issue}", fg="red"))
    click.echo()
    click.echo(click.style(result.summary(), fg="red", bold=True))
    click.echo("  Run ``deck-catalog <template>`` to see available layouts + idx.")
    sys.exit(1)


@cli.command(name="deck-build")
@click.argument("spec", type=click.Path(exists=True, dir_okay=False))
@click.option("--out", "-o", "output", type=click.Path(), default=None,
              help="Output PPTX path (default: <output_dir>/<spec stem>_<YYYYMMDD>.pptx)")
@click.option("--render", is_flag=True, default=False,
              help="After building, render slides to PNG via PowerPoint COM "
                   "(Windows + PowerPoint + pywin32; the visual-verify step).")
def deck_build(spec, output, render):
    """Build a PPTX deck from a spec YAML.

    Resolves the template from the spec's ``meta.pack`` + ``meta.template``
    via the per-seat ``config/decks.yaml`` (env-var paths to OneDrive).
    """
    from ..engine.decks import BuildError, DecksConfigError, build_from_spec

    spec_path = Path(spec).resolve()
    output_path = Path(output).resolve() if output else None

    click.echo()
    click.echo(click.style("Deck build", fg="cyan", bold=True))
    click.echo("=" * 60)
    click.echo(f"  spec   : {spec_path}")
    if output_path:
        click.echo(f"  output : {output_path}")

    try:
        report = build_from_spec(spec_path, output_path=output_path)
    except (BuildError, DecksConfigError) as exc:
        click.echo()
        click.echo(click.style(f"ERROR: {exc}", fg="red", bold=True))
        sys.exit(1)

    click.echo()
    click.echo(f"  template : {report.template_path}")
    click.echo(f"  slides   : {report.slide_count}")
    click.echo(f"  output   : {report.output_path}")
    if report.warnings:
        click.echo()
        click.echo(click.style(f"  {len(report.warnings)} warning(s):", fg="yellow"))
        for w in report.warnings:
            click.echo(f"    - {w}")
    click.echo()
    click.echo(click.style("BUILT.", fg="green", bold=True))

    if render:
        _render_deck(report.output_path)


def _render_deck(output_path: Path) -> None:
    """Best-effort visual-verify: render the built deck to PNG via the
    PowerPoint-COM renderer in tools/deck-render. Skips with a hint if the
    renderer or PowerPoint is unavailable (non-Windows, no pywin32)."""
    import subprocess

    repo_root = Path(__file__).resolve().parents[2]
    renderer = repo_root / "tools" / "deck-render" / "render_pptx.py"
    if not renderer.exists():
        click.echo(click.style(
            f"  --render skipped: renderer not found at {renderer}", fg="yellow"))
        return

    png_dir = output_path.parent / f"{output_path.stem}_render"
    click.echo()
    click.echo(click.style(f"Render -> {png_dir}", fg="cyan", bold=True))
    proc = subprocess.run(
        [sys.executable, str(renderer), str(output_path), str(png_dir)],
        capture_output=True, text=True,
    )
    if proc.returncode == 0:
        click.echo(proc.stdout.strip())
        click.echo(click.style("RENDERED.", fg="green", bold=True))
    else:
        click.echo(click.style(
            "  --render failed (PowerPoint COM needs Windows + PowerPoint + "
            "pywin32). The deck built fine; render manually if needed.",
            fg="yellow"))
        if proc.stderr.strip():
            click.echo(f"    {proc.stderr.strip().splitlines()[-1]}")


# =============================================================================
# Data operations — command-first REST path (no MCP)
# =============================================================================
#
# These commands are the runnable backbone of the data-ops skills
# (/databricks-query, /databricks-run, /fabric-notebook-deploy). The skills lead
# with `python -m core.cli <cmd>` as the path of least resistance; the MCP tools
# stay the agent's preferred path when a server is loaded. The CLI itself has no
# MCP — it always goes through the core connectors over REST, reading host/token
# (Databricks) or az/SP auth (Fabric) from the project's credentials.yaml.


def _overlay_or_none(config: ProjectConfig, env: str | None) -> dict:
    """Load the env overlay, tolerating a missing file (returns {})."""
    if not env:
        return {}
    try:
        return load_overlay(config.root, env)
    except FileNotFoundError:
        return {}


def _render_table(columns: list[str], rows: list, limit: int = 50) -> None:
    """Print columns + rows as a compact markdown table, truncated at ``limit``."""
    if not columns:
        click.echo("(no columns returned)")
        return
    click.echo("| " + " | ".join(columns) + " |")
    click.echo("| " + " | ".join("---" for _ in columns) + " |")
    for row in rows[:limit]:
        cells = ["" if v is None else str(v) for v in row]
        click.echo("| " + " | ".join(cells) + " |")


@cli.command(name="databricks-query")
@click.argument("sql")
@click.option("--project", "-p", default=None,
              help="Project root (default: nearest ancestor)")
@click.option("--env", "-e", default=None,
              help="Env whose catalog/schema become defaults for unqualified names")
@click.option("--warehouse", "-w", "warehouse_id", default=None,
              help="SQL warehouse id (else overlay databricks.sql_warehouse_id, "
                   "else auto-pick the best available)")
@click.option("--catalog", default=None, help="Default catalog override")
@click.option("--schema", default=None, help="Default schema override")
def databricks_query(sql, project, env, warehouse_id, catalog, schema):
    """Run a SQL statement on a Databricks SQL warehouse (REST).

    Command backbone for /databricks-query. Resolves the warehouse in the
    order --warehouse > overlay databricks.sql_warehouse_id > auto-pick, runs
    the statement to completion, and prints the result as a markdown table.
    """
    config = _load(project)
    # Build the databricks connector directly — query is not bound to a sync scope.
    db_host = config.platforms.get("databricks", {}).get("host", "")
    connector = DatabricksConnector.from_credentials(
        load_credentials(config.root), host=db_host
    )

    overlay = _overlay_or_none(config, env)
    if env:
        env_db = config.env_config(env).get("platforms", {}).get("databricks", {})
        catalog = catalog or env_db.get("catalog")
        schema = schema or env_db.get("schema")

    warehouse_id = (
        warehouse_id
        or overlay.get("databricks", {}).get("sql_warehouse_id")
        or connector.pick_warehouse()
    )

    # Classify on the first keyword: only DDL/DML is logged (read-only would be noise).
    first_kw = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else ""
    is_write = first_kw in ("CREATE", "DROP", "INSERT", "UPDATE", "DELETE",
                            "MERGE", "ALTER", "TRUNCATE", "REPLACE")

    click.echo(click.style("\nade-ops databricks-query", fg="cyan", bold=True))
    click.echo("=" * 60)
    click.echo(f"  warehouse : {warehouse_id}")
    if catalog or schema:
        click.echo(f"  defaults  : catalog={catalog or '-'} schema={schema or '-'}")
    click.echo()

    try:
        out = connector.run_query(sql, warehouse_id, catalog=catalog, schema=schema)
    except Exception as exc:
        if is_write:
            _append_ops_log(config, "SQL-WRITE", env, warehouse_id, "fail",
                            detail=sql.strip()[:80])
        click.echo(click.style(f"Query failed: {exc}", fg="red", bold=True))
        raise

    _render_table(out["columns"], out["rows"])
    click.echo()
    shown = min(len(out["rows"]), 50)
    click.echo(f"  {shown} of {out['row_count']} row(s)"
               + (" (truncated)" if out["truncated"] else ""))
    # Only DDL/DML is logged — read-only queries would be ops.log noise.
    if is_write:
        _append_ops_log(config, "SQL-WRITE", env, warehouse_id, "ok",
                        detail=sql.strip()[:80])


@cli.command(name="databricks-run")
@click.argument("notebook")
@click.option("--project", "-p", default=None)
@click.option("--env", "-e", default=None,
              help="Env whose workspace_path prefixes a relative --notebook path")
@click.option("--cluster", "-c", "cluster_id", default=None,
              help="Existing cluster id (else overlay databricks.cluster_id)")
@click.option("--param", "params", multiple=True, metavar="KEY=VALUE",
              help="Notebook base parameter (repeatable)")
@click.option("--timeout", "timeout_seconds", type=int, default=3600,
              help="Per-run timeout in seconds (default 3600)")
def databricks_run(notebook, project, env, cluster_id, params, timeout_seconds):
    """Run a single notebook as a one-time job run on a cluster (REST).

    Command backbone for /databricks-run. The notebook must already be in the
    workspace (deploy via /ops-push or /databricks-deploy first). Resolves the
    cluster from --cluster or overlay databricks.cluster_id.
    """
    config = _load(project)
    db_host = config.platforms.get("databricks", {}).get("host", "")
    connector = DatabricksConnector.from_credentials(
        load_credentials(config.root), host=db_host
    )

    overlay = _overlay_or_none(config, env)
    cluster_id = cluster_id or overlay.get("databricks", {}).get("cluster_id")
    if not cluster_id:
        raise click.ClickException(
            "No cluster id. Pass --cluster or set databricks.cluster_id in the overlay."
        )

    # Prefix a relative notebook path with the env's workspace_path.
    nb_path = notebook
    if env and not notebook.startswith("/"):
        ws_path = (
            config.env_config(env).get("platforms", {})
            .get("databricks", {}).get("workspace_path", "")
        )
        if ws_path:
            nb_path = f"{ws_path.rstrip('/')}/{notebook}"

    base_parameters = dict(p.split("=", 1) for p in params if "=" in p) or None

    click.echo(click.style("\nade-ops databricks-run", fg="cyan", bold=True))
    click.echo("=" * 60)
    click.echo(f"  notebook : {nb_path}")
    click.echo(f"  cluster  : {cluster_id}")
    click.echo()

    try:
        run = connector.run_notebook(
            nb_path,
            existing_cluster_id=cluster_id,
            base_parameters=base_parameters,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        _append_ops_log(config, "RUN", env, "notebooks", "fail",
                        detail=f"{nb_path.split('/')[-1]}")
        click.echo(click.style(f"Run failed: {exc}", fg="red", bold=True))
        raise

    state = run.get("state", {})
    click.echo(click.style(
        f"SUCCESS — {state.get('result_state', 'TERMINATED')}", fg="green", bold=True
    ))
    run_page = run.get("run_page_url")
    if run_page:
        click.echo(f"  run page : {run_page}")
    _append_ops_log(config, "RUN", env, "notebooks", "ok",
                    detail=f"{nb_path.split('/')[-1]} (1 ok, 0 fail)")


@cli.command(name="fabric-notebook-deploy")
@click.argument("local_path", type=click.Path(exists=True, dir_okay=False), required=False)
@click.option("--project", "-p", default=None)
@click.option("--env", "-e", default=None,
              help="Env resolving the Fabric workspace from overlay/platforms")
@click.option("--workspace", "-w", "workspace_id", default=None,
              help="Fabric workspace id override")
@click.option("--name", "display_name", default=None,
              help="Display name (default: source filename stem)")
@click.option("--list", "list_only", is_flag=True,
              help="List notebooks in the workspace and exit (read-only)")
@click.option("--yes", "-y", is_flag=True, help="Skip the confirm-before-deploy prompt")
def fabric_notebook_deploy(local_path, project, env, workspace_id, display_name,
                           list_only, yes):
    """Deploy a .py/.ipynb notebook to a Fabric workspace (REST).

    Command backbone for /fabric-notebook-deploy. Converts a Databricks-style
    .py via core/parsers/databricks_to_ipynb, then create/update the Fabric
    Notebook item. Structural conversion only — semantic rewrites belong to
    /migration-assess.
    """
    import base64
    import json as _json

    from ..parsers.databricks_to_ipynb import read_and_convert

    config = _load(project)

    # Resolve workspace: --workspace > overlay power_bi.workspace_id > platforms.fabric.
    overlay = _overlay_or_none(config, env)
    if not workspace_id:
        workspace_id = overlay.get("power_bi", {}).get("workspace_id")
    if not workspace_id and env:
        workspace_id = (
            config.env_config(env).get("platforms", {})
            .get("fabric", {}).get("workspace_id")
        )
    if not workspace_id:
        raise click.ClickException(
            "No Fabric workspace id. Pass --workspace or set "
            "power_bi.workspace_id (overlay) / platforms.fabric.workspace_id."
        )

    env_platform_auth = None
    if env:
        env_platform_auth = (
            config.env_config(env).get("platforms", {})
            .get("fabric", {}).get("auth")
        )
    connector = FabricConnector.from_credentials(
        load_credentials(config.root), env_platform_auth=env_platform_auth
    )

    if list_only:
        items = connector.client.list_items(workspace_id, item_type="Notebook")
        click.echo(click.style(
            f"\nNotebooks in workspace {workspace_id}", fg="cyan", bold=True))
        click.echo("=" * 60)
        for it in items:
            click.echo(f"  {it.get('displayName')}  ({it.get('id')})")
        if not items:
            click.echo("  (none)")
        return

    if not local_path:
        raise click.ClickException("LOCAL_PATH is required unless --list is set.")

    src = Path(local_path).resolve()
    display_name = display_name or src.stem
    notebook_content = read_and_convert(src)

    parts = [
        {
            "path": "notebook-content.ipynb",
            "payload": base64.b64encode(
                _json.dumps(notebook_content).encode()
            ).decode(),
            "payloadType": "InlineBase64",
        },
        {
            "path": ".platform",
            "payload": base64.b64encode(_json.dumps({
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
                "metadata": {"type": "Notebook", "displayName": display_name},
                "config": {"version": "2.0",
                           "logicalId": "00000000-0000-0000-0000-000000000000"},
            }).encode()).decode(),
            "payloadType": "InlineBase64",
        },
    ]
    definition = {"format": "ipynb", "parts": parts}

    existing = connector.client.find_item_by_name(workspace_id, "Notebook", display_name)
    action = "update" if existing else "create"

    click.echo(click.style("\nade-ops fabric-notebook-deploy", fg="cyan", bold=True))
    click.echo("=" * 60)
    click.echo(f"  source    : {src}")
    click.echo(f"  workspace : {workspace_id}")
    click.echo(f"  name      : {display_name}")
    click.echo(f"  action    : {action}{' ' + existing['id'] if existing else ''}")
    click.echo()

    if not yes:
        if not click.confirm("Proceed?", default=False):
            click.echo("Aborted.")
            sys.exit(0)

    try:
        if existing:
            connector.client.update_item_definition(
                workspace_id, existing["id"], definition)
            item_id = existing["id"]
        else:
            result = connector.client.create_item(
                workspace_id, display_name=display_name,
                item_type="Notebook", definition=definition)
            item_id = result.get("id", "<unknown>")
    except Exception as exc:
        _append_ops_log(config, "FABRIC-NB-DEPLOY", env, display_name, "fail",
                        detail=f"{action}: {type(exc).__name__}")
        click.echo(click.style(f"Deploy failed: {exc}", fg="red", bold=True))
        raise

    click.echo(click.style(
        f"Deployed ({action}) — item id: {item_id}", fg="green", bold=True))
    _append_ops_log(config, "FABRIC-NB-DEPLOY", env, display_name, "ok",
                    detail=f"{action} {item_id} ws={workspace_id}")


@cli.command(name="dax")
@click.argument("query")
@click.option("--project", "-p", default=None,
              help="Project root (default: nearest ancestor)")
@click.option("--env", "-e", required=True, help="Target environment")
@click.option("--model", "-m", required=True,
              help="Dataset alias defined in overlay power_bi.datasets")
@click.option("--output", "-o", "output_fmt", default="table",
              type=click.Choice(["table", "json"]),
              help="Output format: table (default) or json")
def dax_query(query, project, env, model, output_fmt):
    """Execute a DAX query against a Power BI semantic model (REST).

    QUERY is a DAX expression. Prefix with ``@`` to read from a file:
    ``@path/to/query.dax``.

    Command backbone for live Power BI investigation. Resolves
    workspace_id from overlay ``power_bi.model_workspace_id`` and dataset_id
    from overlay ``power_bi.datasets.{model}``. Read-only — never writes
    to the workspace or the project state.

    \b
    Examples:
      python -m core.cli dax "EVALUATE TOPN(5, fct_sales)" \\
          --project distributions/reference/projects/acme-powerbi --env dev --model AcmeSales

      python -m core.cli dax @queries/probe.dax \\
          --project ... --env cert --model AcmeSales --output json
    """
    # @file syntax — read DAX from a file
    if query.startswith("@"):
        query_path = Path(query[1:])
        if not query_path.exists():
            raise click.ClickException(f"Query file not found: {query_path}")
        query = query_path.read_text(encoding="utf-8").strip()

    config = _load(project)
    overlay = _overlay_or_none(config, env)
    pbi = overlay.get("power_bi") or {}

    # Resolve workspace_id: overlay.power_bi.model_workspace_id > env platforms
    workspace_id = pbi.get("model_workspace_id")
    if not workspace_id:
        workspace_id = (
            config.env_config(env).get("platforms", {})
            .get("fabric", {}).get("workspace_id")
        )
    if not workspace_id:
        raise click.ClickException(
            "No workspace id found. Set overlay power_bi.model_workspace_id."
        )

    # Resolve dataset_id from the static overlay datasets map
    datasets: dict = pbi.get("datasets") or {}
    dataset_id = datasets.get(model)
    if not dataset_id:
        available = list(datasets.keys())
        raise click.ClickException(
            f"Dataset alias {model!r} not in overlay power_bi.datasets. "
            f"Available: {available if available else '(none — add power_bi.datasets to overlay)'}."
        )

    env_platform_auth = (
        config.env_config(env).get("platforms", {}).get("fabric", {}).get("auth")
    )
    connector = FabricConnector.from_credentials(
        load_credentials(config.root), env_platform_auth=env_platform_auth
    )

    query_preview = query[:80] + ("..." if len(query) > 80 else "")
    click.echo(click.style("\nade-ops dax", fg="cyan", bold=True))
    click.echo("=" * 60)
    click.echo(f"  workspace : {workspace_id}")
    click.echo(f"  dataset   : {dataset_id}  ({model})")
    click.echo(f"  query     : {query_preview}")
    click.echo("=" * 60)

    try:
        result = connector.execute_dax(workspace_id, dataset_id, query)
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc

    rows = result["rows"]
    columns = result["columns"]

    if output_fmt == "json":
        import json as _json
        click.echo(_json.dumps(rows, indent=2, default=str))
        click.echo(f"\n  {len(rows)} row(s)")
        return

    # Default: markdown table
    if not rows:
        click.echo("  (no rows returned)")
        return

    _render_table(columns, [[row.get(c) for c in columns] for row in rows])
    click.echo(f"\n  {len(rows)} row(s)")


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

    # 2b. External tooling (informational — never fails the preflight)
    _preflight_tooling()

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


def _preflight_tooling() -> None:
    """Probe optional external tools (node, az) and surface per-OS install hints.

    These are conveniences, not ade-ops hard requirements, so they are reported
    informationally and never fail the preflight: ``node``/``npm`` back Claude
    Code + MCP servers; ``az`` backs the Fabric / Azure auth path. A fresh
    clean-room machine often lacks them (and has ``winget`` off PATH), which is
    a recurring onboarding snag — surfacing them here saves trial-and-error.
    """
    import shutil

    hints = {
        "win32": {
            "node": "winget install OpenJS.NodeJS.LTS  (or https://nodejs.org)",
            "az": "winget install Microsoft.AzureCLI",
        },
        "darwin": {"node": "brew install node", "az": "brew install azure-cli"},
        "linux": {
            "node": "use your package manager or https://nodejs.org",
            "az": "https://learn.microsoft.com/cli/azure/install-azure-cli",
        },
    }
    os_hints = hints.get(sys.platform, hints["linux"])
    for tool, why in (("node", "Claude Code + MCP"), ("az", "Fabric / Azure auth")):
        path = shutil.which(tool)
        if path:
            _check(f"tool: {tool}", True, path)
        else:
            mark = click.style("[warn]", fg="yellow")
            click.echo(
                f"  {mark} {'tool: ' + tool:32} "
                f"not found ({why}, optional) — {os_hints.get(tool, '')}"
            )


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
        # "reachable ✓" must not imply the workspace is the intended one. Surface
        # WHO the token authenticates as and WHERE host/token came from, then
        # flag a token-identity vs target mismatch — a token inherited from
        # ambient env vars can silently point a demo at a client's production
        # workspace (TICK-008).
        return _preflight_databricks_identity(config, connector, ws_path)
    except Exception as e:
        _check(f"databricks reachable [{env}]", False, f"{type(e).__name__}: {e}")
        return 1


def _raw_config_value(path: Path, *keys: str) -> str | None:
    """Read a dotted key from a YAML file WITHOUT ${VAR} resolution.

    Returns the raw string (possibly still containing ``${VAR}``) so preflight
    can report provenance — whether a value is a project-config literal or was
    resolved from an ambient environment variable. Returns None if the file or
    key is absent / not a string.
    """
    try:
        import yaml

        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    node = raw
    for k in keys:
        if not isinstance(node, dict):
            return None
        node = node.get(k)
    return node if isinstance(node, str) else None


def _provenance(raw_value: str | None) -> str:
    """Describe where a resolved value came from, based on its raw form."""
    if raw_value is None:
        return "source unknown"
    import re

    m = re.search(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", raw_value)
    if m:
        return f"resolved from ${{{m.group(1)}}} — ambient env, NOT this project's config"
    return "project config literal"


def _email_in_workspace_path(ws_path: str) -> str | None:
    """Extract an email from a ``/Users/<email>/...`` workspace path, if any."""
    import re

    m = re.search(r"/Users/([^/]+@[^/]+?)/", ws_path.rstrip("/") + "/")
    return m.group(1) if m else None


def _preflight_databricks_identity(config: ProjectConfig, connector, ws_path: str) -> int:
    """Surface token identity + host/token provenance; flag identity mismatch.

    Returns a failure count: 0 when identity is surfaced and either matches the
    intended target or no target is determinable; 1 when the identity probe
    fails or the token authenticates as a different account than the target.
    """
    proj_yaml = config.root / "config" / "project.yaml"
    creds_yaml = config.root / "config" / "credentials.yaml"
    host_raw = _raw_config_value(proj_yaml, "platforms", "databricks", "host")
    token_raw = _raw_config_value(creds_yaml, "databricks", "token")

    try:
        me = connector.client.current_user()
    except Exception as e:
        _check(
            "databricks identity",
            False,
            f"could not resolve token identity: {type(e).__name__}: {e}",
        )
        return 1
    identity = me.get("userName") or me.get("displayName") or "<unknown>"

    click.echo(f"        token identity : {identity}")
    click.echo(f"        host           : {connector.client.host}  ({_provenance(host_raw)})")
    click.echo(f"        token          : {_provenance(token_raw)}")

    # Mismatch check only when a target identity is determinable: the demo's
    # DEMO_USER_EMAIL, or an email embedded in a /Users/<email>/ workspace path.
    # Shared-folder targets (/Shared/...) have no owning identity → informational
    # surface only, no mismatch gate.
    target = os.environ.get("DEMO_USER_EMAIL") or _email_in_workspace_path(ws_path)
    if not target:
        return 0
    if target.strip().lower() == identity.strip().lower():
        _check("identity matches target", True, identity)
        return 0
    _check(
        "identity matches target",
        False,
        f"token authenticates as '{identity}' but the target is '{target}' — "
        f"this token/workspace may belong to a DIFFERENT account than intended. "
        f"Confirm this is the workspace you mean for project "
        f"'{config.client}/{config.name}' BEFORE any push.",
    )
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
