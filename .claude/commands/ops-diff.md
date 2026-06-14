# /ops-diff — Compare Local vs Remote State

You are executing a **diff** operation: comparing assembled local files (`src/` + overlay + patches) against the last pulled remote state (`state/{env}/{scope}/`).

This skill is a thin wrapper around the ade-ops CLI: `python -m core.cli diff`.

## Usage

```
/ops-diff                                # interactive — ask for env and scope
/ops-diff dev notebooks                  # diff notebooks for dev
/ops-diff cert notebooks                 # diff notebooks for cert
/ops-diff prod power_bi                  # diff power_bi for prod
/ops-diff cert notebooks --file foo.py   # filter to a specific file
```

## Arguments

- `$ARGUMENTS` — optional: `{env} {scope}` with optional `--file {filter}`

Parse arguments from: `$ARGUMENTS`.

## Behavior

### Step 1: Resolve Project

Find the active project (nearest ancestor of cwd with `config/project.yaml`).
Pass it via `--project {project_root}` to the CLI.

### Step 2: Resolve Environment & Scope

If not provided, ask the user. Use `python -m core.cli status` to list available env × scope combinations.

### Step 3: Check State Exists

If `state/{env}/{scope}/` is empty or missing, the CLI will warn. Surface:

> No state for {env}/{scope}. Run `/ops-pull {env} {scope}` first to download the current remote state.

Do not proceed without state — diff needs something to compare against.

### Step 4: Execute Diff

```bash
python -m core.cli diff --project {project_root} --env {env} --scope {scope}
```

Optional flags:
- `--filter {pattern}` to narrow to specific files
- `--no-content` to suppress unified diff output (summary only)

For `all`, iterate over the project's scopes.

### Step 5: Interpret & Report

The CLI summary uses these markers:

| Marker | Meaning |
|---|---|
| `+` (local-only) | Files in assembled `src/` not in state — would be **added** by push |
| `-` (remote-only) | Files in state not in assembled `src/` — exist remotely but not locally |
| `~` (modified) | Files differ between local and state — would be **updated** by push |
| `=` (identical) | Files match — no action needed |

After the diff, suggest next steps:

- Changes present → "Run `/ops-push {env} {scope}` to deploy."
- In sync → "No changes to push."
- Remote-only files → "These exist remotely but not in `src/`. Push **will not delete them** — manual cleanup if unwanted."

## Safety

- Diff is **read-only**. Reads `src/`, overlays, patches, and `state/`. Writes nothing.
- Always safe to run. No confirmation needed.

## Error Handling

- **No state** → direct user to `/ops-pull` first
- **Empty src/** → warn that everything will show as remote-only
- **Overlay not found** → show the error, suggest checking `overlays/`
