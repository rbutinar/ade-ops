---
status: experimental
since: 2026-05-27
related: ops-init, ops-feedback
---

# /ade-ops-onboarding — Scenario-aware onboarding

> **Status: `experimental`**. F1 ships this skill as an MVP scenario picker that routes the user to the appropriate manual quickstart doc. The full interactive wizard (auto-scaffold, identity wiring, first preflight, first pull) is deferred to F2.

## What this skill does (F1 MVP)

1. Detects whether this is a first run (sentinel-based)
2. Asks the user which of the three V1 scenarios fits their environment
3. Prints a redirect to the corresponding `docs/quickstart/<scenario>.md`
4. On first run, prompts the user for structured feedback at the end (what worked, what was confusing, what was missing) — routes to `/ops-feedback` or a GitHub Issue

The skill does **not yet** auto-scaffold a distribution, wire identity, run preflight, or execute the first pull. Those steps are documented in the quickstart docs and must be done manually in F1. They land in F2.

## Three onboarding scenarios in V1

| Scenario slug | When to pick it |
|---|---|
| `databricks-to-powerbi` (default) | Databricks + Power BI (Pro/Premium). End-to-end notebooks + PBIR reports + semantic models. |
| `databricks-to-fabric` | Databricks + Microsoft Fabric tenant. Multi-platform pipelines with Fabric as consumer layer. |
| `databricks-only` | Only Databricks. No PBI/Fabric. Notebook + job deployment per environment. |

Future scenarios (`fabric-only`, `playground-zero-setup` with synthetic data) are tracked for V2/V3.

## First-run detection (sentinel)

The skill checks for `distributions/<distribution-slug>/.ade-ops-onboarding-done`:

- **First run** (sentinel absent): verbose scenario picker with explanation of each choice, end-of-run feedback prompt, creates sentinel
- **Subsequent runs** (sentinel present): normal mode, no feedback prompt, optional `--add-scope` flag (planned F2)

Rationale: the first setup of a distribution concentrates the friction and ambiguity. Capturing feedback once (at first run) balances signal/noise.

## Behavior steps

### Step 0 — Detect first run

Look for `distributions/<slug>/.ade-ops-onboarding-done`. If absent, this is a first run — verbose mode + feedback prompt enabled. If present, quick mode.

If multiple distributions exist (none initially in the public clone, only `reference/`), ask the user which to onboard against.

### Step 1 — Identify user type

Ask:

> Are you setting up ade-ops as a **user** (clone, run, operate your own instance) or a **contributor** (planning to send PRs back to the framework)?

Routing:

- **User**: skip dev tooling questions (pre-commit, linters, test runners). Focus on the operational setup.
- **Contributor**: include dev tooling setup pointer to `CONTRIBUTING.md` (branch strategy, conventional commits, tests).

In F1 the difference is just an extra pointer at the end. In F2 the contributor branch installs pre-commit hooks + sets up the test environment.

### Step 2 — Scenario picker

Present the three V1 scenarios as a numbered list. Default selection is `databricks-to-powerbi` (most common). The user picks one.

### Step 3 — Print quickstart redirect

Output:

```
Scenario chosen: <slug>

Manual quickstart: docs/quickstart/<slug>.md

Estimated time: <X minutes>

Next steps:
  1. Open docs/quickstart/<slug>.md in your editor
  2. Follow steps 1-N to scaffold the distribution, wire identity, and run the first pull
  3. Return here and run `/ops-feedback` to report any friction

In F2, this skill will execute steps 1-N automatically.
```

### Step 3.5 — MCP configuration + smoke test (recommended)

Before handing off to the quickstart, walk the operator through copying
`.mcp.example.json` → `.mcp.json` and verifying that the wrapped MCP
servers actually load. Without this step a fresh seat looks ready but
operations silently fall back to direct REST (because `.mcp.json` was
never copied from the example).

Sub-steps:

1. **Check `.mcp.json` exists**: `Test-Path .mcp.json`. If missing,
   propose `Copy-Item .mcp.example.json .mcp.json` and walk the operator
   through replacing `<your-user>` placeholders with their Windows
   username.

2. **Show diff if both exist**: when `.mcp.json` already exists, run
   `git diff --no-index .mcp.example.json .mcp.json` to surface what's
   already configured vs the template defaults. The operator decides
   whether to update.

3. **Per-server prerequisites** — surface the `_setup_*_prereq` notes
   from `.mcp.example.json` for each server the chosen scenario needs:
   - `dde` (Databricks AI Dev Kit): venv + clone of
     `databricks-solutions/ai-dev-kit` + `[DEMO]` profile in `~/.databrickscfg`.
   - `serena` (Power BI Modeling MCP): VSIX install at
     `C:/MCPServers/PowerBIModelingMCP_x64/`.
   - `playwright`: Node.js LTS on PATH + dedicated Edge profile dir
     (Strategy A from `core/playbooks/playwright-pbi-loop.md`).

4. **Restart Claude Code** — `.mcp.json` is read at process start, so
   the operator must close and relaunch Claude Code for the servers to
   load. Surface this explicitly.

5. **Smoke test** — after relaunch, propose the smoke checks that
   confirm each server is alive:
   - `mcp__dde__get_current_user` → returns Databricks identity if `dde`
     loaded.
   - `mcp__playwright__browser_navigate` to `https://app.powerbi.com/`
     → SSO picker appears if `playwright` loaded.
   - `mcp__serena__model_operations` with a list-only payload → confirms
     `serena` loaded (only relevant if scenario uses `/powerbi-model-edit`).

   If any smoke check returns "tool not available", the corresponding
   `.mcp.json` entry needs review (wrong path, missing prereq, etc.).
   Walk the operator back through the relevant `_setup_*_prereq` note.

6. **Log the discovery** — append `MCP-SMOKE | - | - : <pass-count>/3 servers loaded | <ok|partial|fail>` to the project `ops.log`.

This step is recommended but not blocking — operators who explicitly
want REST-only operation (no MCP) can skip it.

### Step 4 — Feedback prompt (first run only)

If this is a first run, after the user has had time to follow the quickstart (return-trip), prompt:

> Did the onboarding work end-to-end? What was confusing? What was missing?

Route the structured response to `/ops-feedback` (Claude Code users) or to a GitHub Issue using the `feedback.yml` template (non-Claude users).

### Step 5 — Create sentinel

Touch `distributions/<slug>/.ade-ops-onboarding-done` with the current timestamp + scenario slug.

## Anti-goals (F1)

- **No automatic scaffolding** — F1 MVP redirects to manual quickstart. F2 implements the wizard.
- **No identity wiring** — the user sets `DATABRICKS_TOKEN`, runs `az login`, etc, themselves following the quickstart.
- **No first pull execution** — quickstart documents the command; user runs it.
- **No multi-scenario blending** — pick one. If you need both Databricks→Power BI and Databricks→Fabric, set up two projects under the same distribution.

## Preview tracking — known unknowns (F1)

1. **Sentinel location**: assumes the user has already scaffolded a distribution slug. If no distribution exists yet, where does the sentinel live? F2 design open question.
2. **Multi-distribution clones**: the public reference clone ships only `distributions/reference/`. Real users may add their own distribution alongside. The skill picks `reference` as default; needs refinement for multi-distro setups.
3. **User vs contributor branching**: the branch is informational in F1 (different end-of-run pointer). F2 will install pre-commit hooks + test dependencies for the contributor branch.
4. **Feedback prompt timing**: in F1 the feedback prompt fires immediately after the redirect, not after the user has actually attempted the quickstart. Real return-trip timing requires session-resume which Claude Code skills don't expose yet.
5. **Add-scope flag**: `--add-scope powerbi` to extend an existing distribution post-onboarding is planned but not implemented.

## Status — promotion criteria

Promotion from `experimental` to `preview`:

1. At least 2 onboardings completed end-to-end by users other than the maintainer, across at least 2 of the 3 scenarios
2. Feedback prompt outputs land as GitHub Issues or `/ops-feedback` files without manual reformatting
3. Sentinel-based first-run detection works as designed (subsequent invocations skip the feedback prompt)
4. F2 design for auto-scaffold + identity wiring is committed (this skill becomes the wizard entry point)

Promotion from `preview` to `stable`:

1. F2 auto-scaffold lands and replaces the manual-redirect step
2. 5+ onboardings without manual remediation
3. All preview-tracking items above resolved
4. At least one onboarding by a contributor (PR follow-up) successful

## Related

- [`/ops-init`](ops-init.md) — lower-level scaffolding (skipped by the F1 MVP, called directly by F2 wizard)
- [`/ops-feedback`](ops-feedback.md) — feedback capture (invoked at end-of-onboarding if first run)
- [`docs/quickstart/databricks-to-powerbi.md`](../../docs/quickstart/databricks-to-powerbi.md) — manual quickstart
- [`docs/quickstart/databricks-to-fabric.md`](../../docs/quickstart/databricks-to-fabric.md) — manual quickstart
- [`docs/quickstart/databricks-only.md`](../../docs/quickstart/databricks-only.md) — manual quickstart

ARGUMENTS: $ARGUMENTS
