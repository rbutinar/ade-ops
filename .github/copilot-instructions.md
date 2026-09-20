# Copilot instructions for ade-ops

ade-ops is a Claude-Code-native framework. Most of the slash commands you'll see
referenced in `.claude/commands/*.md` and in `CLAUDE.md` (e.g. `/ops-pull`,
`/ops-push`, `/pbir-create`, `/databricks-deploy`, `/fabric-warehouse-test`)
**only work in Claude Code**. Copilot should treat them as documentation, not
as invokable commands.

The **CLI is agent-agnostic** — that's the surface you should use to take
action on this repo.

## What works directly with Copilot

```bash
python -m core.cli preflight                                   # env + deps + creds check
python -m core.cli status                                      # env × scope matrix
python -m core.cli pull --env dev --scope notebooks            # download remote state
python -m core.cli push --env dev --scope notebooks --dry-run  # assemble + show what would change
python -m core.cli push --env dev --scope notebooks            # actually deploy
python -m core.cli diff --env dev                              # local vs remote
python -m core.cli publish --distribution reference \
                          --target-dir <path> --dry-run        # sanitized publish gate
```

All operations require a project root with `config/project.yaml` and a
populated `config/credentials.yaml` (copy from `credentials.example.yaml`).

## Repository structure

| Path | What lives here |
|---|---|
| `core/engine/` | Sync engine (config, state, overlay, operations, publish) |
| `core/connectors/` | Platform adapters — Databricks REST, Fabric REST + MSAL |
| `core/platforms/` | Higher-level platform code (Fabric auth, PBI PBIR engine) |
| `core/parsers/` | Notebook + TMDL parsers |
| `core/conventions/` | Sanitization patterns + cross-skill conventions |
| `distributions/{slug}/projects/{project}/src/` | **Author code here** — source of truth |
| `distributions/{slug}/projects/{project}/state/` | **Never author** — mirror pulled from remote |
| `distributions/{slug}/projects/{project}/overlays/` | Env-specific transforms (declarative) |
| `distributions/{slug}/projects/{project}/patches/` | Temporary per-env overrides |
| `docs/quickstart/` | Three scenario walkthroughs (DBR→PBI / DBR→Fabric / DBR-only) |

## Read these for context (in order)

1. **`README.md`** — the public-facing intro + quickstart routing
2. **`distributions/reference/projects/databricks-fabric-migration/CLAUDE.md`** —
   end-to-end workflow for the included sample (medallion on `samples.tpch.*`)
3. **`docs/quickstart/databricks-to-fabric.md`** — the full scenario the
   reference project is built around
4. **`CLAUDE.md`** (root) — repo conventions: `src/` vs `state/` vs `overlays/`,
   the distribution model, framework vs distribution split
5. **`SECURITY.md`** — private disclosure channel; do not open public issues
   for vulnerabilities or data leakage

## What to NEVER do

- **Don't write to `state/`** — it's pulled from remote on every `pull`,
  any local edits are silently lost. Author in `src/`, env-specific
  transforms in `overlays/`.
- **Don't commit `credentials.yaml`** — it's gitignored, contains tokens.
  Use `credentials.example.yaml` as the committed template.
- **Don't push to remote envs without a dry-run + user confirmation first.**
  The CLI supports `--dry-run` precisely for this.
- **Don't bypass `/ops-publish` to push lab content public.** It applies
  sanitization rules from `core/conventions/sanitization-patterns.md`.
  Bypassing means shipping unscrubbed content.

## Conventions

- Python 3.10+. Type hints on public functions. `pathlib.Path` for files,
  `httpx` for HTTP, `pyyaml` for YAML, `click` for CLI.
- Log significant actions to `docs/ops.log` (project-level) — 25+ skills
  document this convention, see e.g. `.claude/commands/ops-push.md`.
- All comments and identifiers in English (always). Conversation: mirror the
  user's language; English by default (see `CLAUDE.md` root).

## Limits of these instructions

This file describes what's *portable* across AI assistants. The full
agent-driven workflow (multi-step orchestrations, role sessions like
`/ops-dev` / `/ops-prod` / `/ops-review`, the `/ade-ops-onboarding`
scenario picker, automatic `/ops-publish` sanitization) lives in
`.claude/commands/*.md` and requires Claude Code. If you're working
with Copilot, use the CLI directly and ask the maintainer when the
intended workflow isn't obvious from the docs above.
