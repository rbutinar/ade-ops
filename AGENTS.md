# AGENTS.md

Generic instructions for AI coding assistants working in this repository.
Tool-agnostic — applies to Aider, Continue, Cline, custom agents, and any
LLM-driven workflow that reads a conventions file at the repo root.

For tool-specific manifests, see:

- **Claude Code**: [`CLAUDE.md`](CLAUDE.md) at the root (rich format, full conventions + slash command catalogue)
- **GitHub Copilot**: [`.github/copilot-instructions.md`](.github/copilot-instructions.md) (auto-loaded as Copilot Chat context)

This file is the fallback used when neither of the above applies.

## What this repo is

`ade-ops` is a local supervisor framework for remote analytics environments
(Databricks, Microsoft Fabric, Power BI). It synchronises a single source of
truth in `src/` to multiple environments via declarative overlays, using a
small Python engine and a `python -m core.cli` surface.

The framework is structured as a generic **core** plus per-client
**distributions**. A distribution never modifies the core — it consumes it.

## The CLI is the agent-agnostic surface

```bash
python -m core.cli preflight                # deps + credentials sanity
python -m core.cli status                   # env × scope matrix + last-pull
python -m core.cli pull --env <env> --scope <scope>
python -m core.cli diff --env <env> --scope <scope>
python -m core.cli push --env <env> --scope <scope> [--dry-run]
python -m core.cli publish --distribution <slug> --target-dir <path> [--dry-run]
```

Always `--dry-run` before any `push` or `publish` that writes to a remote.

## Authoring rules

| Where | What |
|---|---|
| `distributions/{slug}/projects/{project}/src/` | Source of truth. Author code here. |
| `distributions/{slug}/projects/{project}/state/` | Pulled from remote. **Never author.** Any edits are overwritten on next `pull`. |
| `distributions/{slug}/projects/{project}/overlays/{env}.yaml` | Per-env transforms (catalog remap, text replace, exclusions). Declarative, no business logic. |
| `distributions/{slug}/projects/{project}/patches/{env}/` | Temporary env-specific overrides. Should be short-lived. |
| `distributions/{slug}/projects/{project}/local/` | Personal scratch, never deployed. Gitignored. |
| `core/` | Framework code. Client-agnostic. Only modified by the framework maintainer. |

## What this repo guards against

- **Credentials in git** — `credentials.yaml` is gitignored at every level.
  Always use the `credentials.example.yaml` template.
- **Pre-publication leakage** — the `core/engine/publish.py` engine runs
  sanitization rules on every file before it's copied to a public target.
  Refuses publish on BLOCK pattern match. See `SECURITY.md`.
- **Unintended writes to production** — every remote write requires a
  user confirmation. `--dry-run` is the default expected step before any
  state-changing operation.

## Code style

- Python 3.10+
- Type hints on public functions
- `pathlib.Path` (not `os.path`)
- `httpx` for HTTP (not `requests`)
- `pyyaml` for YAML
- `click` for CLI
- English in code, comments, docstrings, commit messages
- Italian only acceptable in conversational interaction with the maintainer

## Where to read next

- `README.md` — public-facing intro + quickstart paths
- `CLAUDE.md` (root) — full conventions (richer than this file)
- `docs/quickstart/` — three concrete scenarios (DBR→PBI, DBR→Fabric, DBR-only)
- `distributions/reference/projects/databricks-fabric-migration/CLAUDE.md` —
  end-to-end sample workflow on Databricks built-in `samples.tpch.*` data
- `SECURITY.md` — private disclosure channel
