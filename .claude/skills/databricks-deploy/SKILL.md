---
name: databricks-deploy
description: Ad-Hoc Raw Upload to Databricks
---

# /databricks-deploy — Ad-Hoc Raw Upload to Databricks

You are executing a **raw upload** of files/folders to a Databricks workspace via MCP.

**This is an escape hatch.** For the normal flow (assembly + overlay transforms + state update), use `/ops-push` instead.

## When to use this vs `/ops-push`

| Use this skill | Use `/ops-push` |
|---|---|
| Upload a single utility script ad-hoc | Deploy a project scope (notebooks/power_bi) |
| Bypass overlay transforms (raw copy) | Apply env-specific transforms (catalog remap, etc.) |
| Target a workspace path outside `scopes.*.path` | Target the configured workspace_path for the env |
| No state tracking needed | State must reflect what was deployed |

If you find yourself reaching for this skill regularly to deploy a project, you should be using `/ops-push` instead.

## Prerequisites

- Databricks MCP server configured (`databricks` in `.mcp.json`)
- The MCP profile must point to the same workspace as the target env
- Project `config/project.yaml` present (used to resolve workspace paths from `{env}`)

## Usage

```
/databricks-deploy                              # interactive — ask source + target
/databricks-deploy {local_path} --env {env}     # deploy a file or folder to env's workspace_path
/databricks-deploy {local_path} --target {ws}   # deploy to an explicit workspace path
```

Arguments via `$ARGUMENTS`:
- `local_path` (required) — file or folder relative to project root
- `--env {env}` — resolve target via `project.yaml` env's `databricks.workspace_path`
- `--target {workspace_path}` — explicit override (mutually exclusive with `--env`)
- `--subfolder {name}` — append a subfolder under the resolved target (e.g. `bronze`, `silver`)

## Behavior

### Step 1: Resolve Project

Find the active project (nearest ancestor of cwd with `config/project.yaml`).

### Step 2: Resolve Source

Resolve `local_path` against the project root. Reject if it points outside the project tree or into `state/` (which is a mirror, not source).

### Step 3: Resolve Target

If `--target` is given, use it verbatim. Otherwise read `project.yaml`:

```yaml
environments.{env}.platforms.databricks.workspace_path
```

Apply env-var expansion if the value contains `${VAR}`.

If `--subfolder` is given, append it: `{workspace_path}/{subfolder}`.

### Step 4: Confirmation

Show the resolved plan and ask:

> **Raw upload — no overlay transforms applied:**
> - Source: {local_path}
> - Target: {workspace_path}
> - Files: {n} files, {size} bytes
>
> ⚠️ This bypasses the assembly pipeline. Use `/ops-push` for structured deploys.
>
> **Proceed?** (yes/no)

For **prod** environments (when resolved via `--env prod`), double-confirm.

**Do NOT proceed without explicit user confirmation.**

### Step 5: Execute Upload

For a folder:
```
mcp__databricks__upload_folder(
  local_folder = "{abs_local_path}",
  workspace_folder = "{target_workspace_path}",
  overwrite = true
)
```

For a single file:
```
mcp__databricks__upload_file(
  local_path = "{abs_local_path}",
  workspace_path = "{target_workspace_path}",
  overwrite = true
)
```

### Step 6: Report & Log

Show success count and any errors per-file.

Append to the project's `ops.log`:

```
{ISO_timestamp} | {role} | DEPLOY-RAW | {env|--} | {local_path} → {workspace_path}: {n} files | {ok|fail}
```

Use `role = ops` unless inside a role session.

## File Types Supported

`.py`, `.sql`, `.scala`, `.r`, `.yaml`, `.json`, `.txt` — the MCP server handles format detection automatically.

## Error Handling

- **MCP `databricks` not available** → ask user to verify `.mcp.json` and restart Claude Code (see ONBOARDING.md step 7)
- **403 / permission denied** → user's PAT lacks write access to the target path
- **Invalid workspace path** → must start with `/Workspace/` or `/Shared/`
- **No `--env` and no `--target`** → ask the user which to use

## Notes

- This skill does NOT update `.state.yaml` — running `/ops-diff` after a raw upload will likely report drift
- For a structured deploy that keeps state in sync, use `/ops-push`
- The `overwrite=true` default means existing files on the workspace will be replaced
