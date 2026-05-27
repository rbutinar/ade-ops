# /ops-status — Project Status Overview

You are executing a **status** operation: showing an overview of a project's environments, sync state, and health.

This skill is a thin wrapper around the ade-ops CLI: `python -m core.cli status`.

## Usage

```
/ops-status                      # all environments for the active project
/ops-status cert                 # status for cert only
```

## Arguments

- `$ARGUMENTS` — optional: `{env}`

Parse arguments from: `$ARGUMENTS`.

## Behavior

### Step 1: Resolve Project

Find the active project (nearest ancestor of cwd with `config/project.yaml`).
Pass it via `--project {project_root}`.

### Step 2: Execute Status

```bash
python -m core.cli status --project {project_root}
```

If a specific env was requested, add `--env {env}`.

### Step 3: Extended Report (read locally, not via CLI)

After the engine status output, add a few lightweight checks the CLI doesn't do:

- **Source overview**: count files in `src/{scope}/` per scope (use `Glob`)
- **Overlay check**: confirm each environment has an overlay file under `overlays/`
- **Recent ops.log entries**: tail the last 5 lines of `{project_root}/ops.log` if present

### Step 4: Suggest Next Actions

Based on the output, suggest:

| Condition | Suggestion |
|---|---|
| State is empty (never pulled) | `/ops-pull {env} {scope}` |
| State is stale (old pull) | `/ops-pull {env} {scope}` to refresh |
| `src/` has content, state exists | `/ops-diff {env} {scope}` to check drift |
| Patches are aging | Consider merging patches back to `src/` |
| No ops.log | First operation will create it |

## Safety

- Status is **read-only**. Reads config, state, and local files. Writes nothing.
- Always safe to run.

## Output Format

The CLI prints something like:

```
============================================================
  <project> Project Status
============================================================

  Env      Scope          Last Pull      Files      Patches
  -------- -------------- -------------- ---------- ----------
  dev      notebooks      2h ago         12         0
  cert     notebooks      1d ago         12         2
  ...
============================================================
```

Append your extended report (source overview, overlays, recent log, suggestions) below the CLI output.
