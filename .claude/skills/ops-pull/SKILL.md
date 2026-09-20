---
name: ops-pull
description: Pull Remote State
---

# /ops-pull — Pull Remote State

You are executing a **pull** operation: downloading the current state of a remote environment into `state/{env}/{scope}/`.

This skill is a thin wrapper around the ade-ops CLI: `python -m core.cli pull`.

## Usage

```
/ops-pull                       # interactive — ask for env and scope
/ops-pull dev notebooks         # pull notebooks from dev
/ops-pull cert notebooks        # pull notebooks from cert
/ops-pull prod power_bi         # pull power_bi from prod
/ops-pull dev                   # pull all scopes from dev
```

## Arguments

- `$ARGUMENTS` — optional: `{env}` or `{env} {scope}`

Parse arguments from: `$ARGUMENTS`.

## Behavior

### Step 1: Resolve Project

Find the active project (nearest ancestor of cwd containing `config/project.yaml`).
If multiple candidate projects exist under the cwd, ask the user which one.

If you already know the project root, pass it explicitly via `--project` to the CLI.
Otherwise, run the CLI from inside the project directory and let it resolve.

### Step 2: Resolve Environment & Scope

If not provided in `$ARGUMENTS`, ask the user. Discover available envs/scopes via:

```bash
python -m core.cli status --project {project_root}
```

(That prints the env × scope matrix.)

If the user passes a single argument, treat it as `{env}` and ask for `{scope}` (or `all`).

### Step 3: Execute Pull

For a single scope:

```bash
python -m core.cli pull --project {project_root} --env {env} --scope {scope}
```

For `all`, iterate over the project's scopes and call the CLI per scope.

Optional pipeline filter: `--filter {pattern}`.

### Step 4: Report & Log

The CLI prints a summary (`[TOTAL] N files pulled, M errors`). Surface that to the user.

Append one line to the project's `ops.log` (create if missing):

```
{ISO_timestamp} | {role} | PULL | {env} | {scope}: {count} files pulled | {ok|fail}
```

Use `role = ops` unless inside a role session (`/ops-dev`, `/ops-prod`, `/ops-review`).

## Safety

- Pull is **read-only** with respect to the remote — only writes to `state/`.
- Always safe to run. No confirmation needed.
- If `state/{env}/{scope}/` already has files and the CLI reports failures, do not silently overwrite — surface the errors.

## Error Handling

- **`PREFLIGHT FAILED` / connection error** → run `python -m core.cli preflight --project {project_root} --env {env}` and report the failing checks
- **No credentials** → tell the user to copy `credentials.example.yaml` → `credentials.yaml` and set `DATABRICKS_TOKEN`
- **Connector not implemented (e.g. fabric)** → inform and skip that scope
