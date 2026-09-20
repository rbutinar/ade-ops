---
name: ops-push
description: Push to Remote Environment
---

# /ops-push — Push to Remote Environment

You are executing a **push** operation: assembling `src/` + overlay + patches and deploying to a remote environment.

**This is a remote write operation. Always confirm before executing.**

This skill is a thin wrapper around the ade-ops CLI: `python -m core.cli push`.

## Usage

```
/ops-push                        # interactive — ask for env and scope
/ops-push dev notebooks          # push notebooks to dev
/ops-push cert notebooks         # push notebooks to cert
/ops-push prod power_bi          # push power_bi to prod (extra confirmation)
/ops-push cert notebooks --dry   # dry run — show what would be pushed
```

## Arguments

- `$ARGUMENTS` — optional: `{env} {scope}` with optional `--dry`

Parse arguments from: `$ARGUMENTS`.

## Behavior

### Step 1: Resolve Project

Find the active project (nearest ancestor of cwd with `config/project.yaml`).
Pass it to the CLI via `--project {project_root}` if you know it.

### Step 2: Resolve Environment & Scope

If not provided in `$ARGUMENTS`, ask the user. Use `python -m core.cli status` to list available env × scope combinations.

### Step 3: Pre-Push Diff (mandatory)

Always show what will change first:

```bash
python -m core.cli diff --project {project_root} --env {env} --scope {scope}
```

If the diff reports **no state** for `{env}/{scope}`, warn:

> No state exists for {env}/{scope}. Cannot show a diff. Consider running `/ops-pull` first so you can review what will change.

If the user wants to proceed without a prior pull, allow it but surface the warning.

### Step 4: Dry Run (if `--dry` in arguments)

```bash
python -m core.cli push --project {project_root} --env {env} --scope {scope} --dry-run
```

Stop here for dry runs — report and exit.

### Step 5: Confirmation

After showing the diff, summarize and ask explicitly:

> **Push summary — {env}/{scope}:**
> - {n} files to upload (added: X, modified: Y)
> - {removed} remote-only files **will NOT be deleted** (push only uploads)
> - Target: {workspace_path}
>
> **Proceed?** (yes/no)

For **prod** environments, double-confirm:

> ⚠️ **PRODUCTION push** — this will modify the live environment. Type `yes` to proceed.

**Do NOT proceed without explicit user confirmation.**

### Step 6: Execute Push

```bash
python -m core.cli push --project {project_root} --env {env} --scope {scope}
```

Optional file filter: `--filter {pattern}`.

### Step 7: Post-Push Pull

After a successful push, refresh state:

```bash
python -m core.cli pull --project {project_root} --env {env} --scope {scope}
```

This ensures `state/` reflects what was actually deployed.

### Step 8: Report & Log

Surface the push count and the post-push pull result. Flag any discrepancy.

Append to the project's `ops.log`:

```
{ISO_timestamp} | {role} | PUSH | {env} | {scope}: {count} files pushed | {ok|fail}
```

Use `role = ops` unless inside a role session.

## Safety Protocol

1. **Always diff first** — show what will change before asking for confirmation
2. **Always confirm** — never push without explicit "yes"
3. **Production double-confirm** — extra warning for prod environments
4. **Post-push pull** — update state to reflect actual remote state
5. **Log everything** — every push is recorded in ops.log
6. **No deletes** — push only uploads; it never deletes remote files

## Error Handling

- **`PREFLIGHT FAILED` / connection error** → run `python -m core.cli preflight --project {project_root} --env {env}` first
- **No credentials** → ask the user to populate `config/credentials.yaml` and set `DATABRICKS_TOKEN`
- **Partial failure** → report which files failed; suggest retrying with `--filter` on those paths
- **Empty src/** → warn there's nothing to push and stop
