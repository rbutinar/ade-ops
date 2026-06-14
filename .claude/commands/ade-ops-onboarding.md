---
status: stable
since: 2026-06-02
description: "ade-ops setup — START HERE on a fresh clone. Scenario-aware onboarding for Databricks with Power BI and/or Microsoft Fabric."
related: ops-init, ops-feedback
---

# /ade-ops-onboarding — Scenario-aware onboarding

> **This is the canonical ade-ops entry point — START HERE on a fresh clone.**
> If your skill picker also shows a generic `team-onboarding` entry, that is a
> built-in Claude Code skill (repo orientation / `ONBOARDING.md`), **not** part
> of ade-ops — use `/ade-ops-onboarding` for ade-ops setup.

> **Status: `experimental`**. F1 ships this skill as an MVP scenario picker that routes the user to the appropriate manual quickstart doc. The full interactive wizard (auto-scaffold, identity wiring, first preflight, first pull) is deferred to F2.

## What this skill does (F1 MVP)

1. Detects whether this is a first run (sentinel-based)
2. Asks two axes — **start state** (build from an empty sandbox vs migrate/operate a real workspace) and **target** (which of the three V1 scenarios) — landing on a matrix cell that fixes the first move (generate+push vs pull+operate)
3. Prints a redirect to the corresponding `docs/quickstart/<scenario>.md`
4. On first run, prompts the user for structured feedback at the end (what worked, what was confusing, what was missing) — routes to `/ops-feedback` or a GitHub Issue

This skill is **Phase 1** (agent-driven) of setup: it assumes the terminal **Phase 0 bootstrap** is done (clone + install Claude Code + launch — see the README) and continues in the **same CLI session**. Claude Desktop is optional — the nicer home for ongoing work once setup is complete, not a mid-flow switch.

The skill does **not yet** auto-scaffold a distribution, wire identity, run preflight, or execute the first pull. Those steps are documented in the quickstart docs and must be done manually in F1. They land in F2.

## Three onboarding scenarios in V1

| Scenario slug | When to pick it |
|---|---|
| `databricks-to-powerbi` (default) | Databricks + Power BI (Pro/Premium), **no Fabric needed**. Notebooks + an Import/DirectQuery semantic model reading Databricks directly + PBIR reports. The broadest fit — Databricks stays your platform, Power BI is the BI layer. Reference project: `distributions/reference/projects/acme-powerbi/`. |
| `databricks-to-fabric` | Databricks + a Microsoft Fabric tenant: the full medallion → Fabric lakehouse → DirectLake semantic model + report chain. Pick it when Fabric/DirectLake is your target BI platform. Needs a Fabric tenant + Azure identity. |
| `databricks-only` | Only Databricks. No Fabric / Power BI. Notebook + job deployment per environment — the **lightest path** (a Databricks workspace, Community Edition works). Reference project: `distributions/reference/projects/playground/`. |

The `playground` project is the minimal-infra slice of the zero-setup experience
(synthetic data, ~5 min on a free Databricks workspace). A fully local
`playground-zero-setup` (DuckDB connector, no cloud at all) and `fabric-only`
are tracked for V2/V3.

## Two axes: what you HAVE × where you're GOING

The scenario above is only one axis (**where you're going** — the target BI
layer). There is a second axis that decides the **first move**: **what you start
with**.

- **Build (greenfield)** — an empty Databricks sandbox, nothing to migrate. ade-ops
  + the agent **author a project from scratch** (we generate synthetic data so
  there's something to operate on), then `push` it up. This is the only honest
  path for a cold evaluator with no data.
- **Migrate / operate (brownfield)** — you already have assets in a real
  Databricks workspace. The first move is `pull` (mirror the remote into `src/`),
  then operate/migrate **your own** data — *not* generate synthetic data.

The matrix (first move + where to start):

| | **Build — empty sandbox** (we generate synthetic data) | **Migrate / operate — your real workspace** (start from `pull`) |
|---|---|---|
| **Databricks-only** | `projects/playground/` — synthetic data → push → run → query (~5 min) | point at your workspace: `pull` → edit → `push` → `/databricks-run` → explore a catalog table with `/databricks-query`. No shipped content needed — this exercises the engine on *your* assets |
| **Databricks + Fabric/BI** | `projects/databricks-fabric-migration/` on synthetic `samples.tpch.*` → full chain (lakehouse, DirectLake model, report) | `pull` your Databricks gold → `/migration-assess` → build the semantic model + report on *your* data |

Ask this **before** (or together with) the target scenario: it changes whether
the first thing we do is *generate + push* (build) or *pull + operate* (migrate).

> **Prerequisites are real — do not conflate "shipped" with "required".** The
> reference distribution ships *zero credentials*, meaning none are **bundled**
> — **not** that none are **required**. Every scenario needs real infrastructure
> the adopter supplies:
> - `databricks-to-fabric`: a Databricks workspace + PAT, **and** a Microsoft
>   Fabric tenant/workspace + Azure identity for the Fabric/Power BI layer.
> - `databricks-to-powerbi`: a Databricks workspace + PAT, **and** Power BI
>   Pro/Premium.
> - `databricks-only`: a Databricks workspace + PAT.
>
> "Synthetic data (TPC-H)" removes the need to *bring your own data*, not the
> need for a *platform to run on*. State this honestly during onboarding.

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

### Step 1.5 — Start state (build vs migrate)

Ask the start-state axis **before** the target scenario — it decides the first move:

> Do you already have assets in a Databricks workspace you want to operate /
> migrate, or are you starting from an empty sandbox?
> - **Empty / just exploring** → we'll *build* a project from scratch (I generate
>   synthetic data so there's something to push and operate on).
> - **I have a real workspace** → we *start from `pull`* and operate **your own**
>   data — no synthetic data generated.

Carry the answer into Step 2: it selects the matrix cell (which reference project
for *build*, or the `pull`-first loop for *migrate*).

### Step 2 — Scenario picker (target × start-state)

Present the three V1 target scenarios as a numbered list. Default selection is `databricks-to-powerbi` (Databricks + Power BI, no Fabric required — the broadest fit; Databricks stays the platform). The user picks one. Combine it with the Step 1.5 start state to land on a matrix cell:

- **Build + Databricks-only** → `projects/playground/` (synthetic → push → run → query).
- **Build + Fabric/BI** → `projects/databricks-fabric-migration/` on `samples.tpch.*`.
- **Migrate + Databricks-only** → point at the user's workspace and run the brownfield loop: `pull` → edit a notebook → `push` → `/databricks-run` → explore a referenced catalog table with `/databricks-query`. This is the most direct proof that ade-ops operates *their* real Databricks; it needs no shipped content.
- **Migrate + Fabric/BI** → `pull` the user's Databricks gold → `/migration-assess` → author the semantic model + report on their data.

If the user says their work is **only on Databricks** (no Fabric, no Power BI), route straight to `databricks-only` — the lightest path: a Databricks workspace (Community Edition works), a PAT, and nothing else. This is the path the "From Zero to Operational on Databricks" onboarding targets. Point them at the dedicated `distributions/reference/projects/playground/` project — a self-contained synthetic dataset (pure Spark, no `samples.*`/CSV) + one analytics notebook, designed to be operational in ~5 minutes (clone → push → run → query). Its `CLAUDE.md` is the step-by-step. (For a richer Databricks-only walkthrough, the medallion notebooks under `databricks-fabric-migration` `src/notebooks/{_setup,silver,gold}` also work standalone with the BI layers skipped.)

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

### Step 3.5 — MCP: a deliberate choice (REST-only vs MCP-enhanced)

Make MCP an **explicit decision**, not a silent skip. Ask the operator:

> Two ways to operate:
> - **REST-only** — works out of the box, no extra setup. The managed skills
>   (pull/push/diff/status, and the data-ops fallbacks for query/run) all run
>   over plain REST from `credentials.yaml`. Pick this to start fast.
> - **MCP-enhanced** — richer live experience (live SQL, Power BI model edits,
>   Playwright browser automation). Requires wiring `.mcp.json` + per-server
>   prerequisites.
>
> Which do you want? (You can add MCP later.)

If **REST-only**: note that data ops use the REST fallback, skip the wiring, and
move on to Step 4. If **MCP-enhanced**: wire **only the servers the scenario uses** —
not the whole template. The lean per-scenario set and the full "where context goes at
startup" map live in [`core/conventions/lean-seat-loadout.md`](../../core/conventions/lean-seat-loadout.md):

| Scenario | Wire | Skip |
|---|---|---|
| Databricks-only | `databricks` | `powerbi`, `playwright` |
| + Power BI / Fabric report deploy | `databricks`, `playwright` | `powerbi` (only if `/powerbi-model-edit`) |
| + live semantic-model editing | `databricks`, `powerbi`, `playwright` | — |

Sub-steps:

1. **Create a lean `.mcp.json`**: `Test-Path .mcp.json`. If missing, copy
   `.mcp.example.json` → `.mcp.json`, replace `<your-user>` placeholders, then
   **delete the server blocks the scenario doesn't need** (table above). A
   Databricks-only seat keeps just `databricks`. Fewer servers = a lighter session.

2. **Show diff if both exist**: when `.mcp.json` already exists, run
   `git diff --no-index .mcp.example.json .mcp.json` to surface what's
   already configured vs the template defaults. The operator decides
   whether to update.

3. **Per-server prerequisites** — surface the `_setup_*_prereq` notes
   from `.mcp.example.json` for each server the chosen scenario needs:
   - `databricks` (Databricks AI Dev Kit): venv + clone of
     `databricks-solutions/ai-dev-kit` + `[DEMO]` profile in `~/.databrickscfg`.
   - `powerbi` (Power BI Modeling MCP): VSIX install at
     `C:/MCPServers/PowerBIModelingMCP_x64/`.
   - `playwright`: Node.js LTS on PATH + dedicated Edge profile dir
     (Strategy A from `core/playbooks/playwright-pbi-loop.md`).

4. **Restart Claude Code** — `.mcp.json` is read at process start, so
   the operator must close and relaunch Claude Code for the servers to
   load. Surface this explicitly.

5. **Smoke test** — after relaunch, propose the smoke checks that
   confirm each server is alive:
   - `mcp__databricks__get_current_user` → returns Databricks identity if `databricks`
     loaded.
   - `mcp__playwright__browser_navigate` to `https://app.powerbi.com/`
     → SSO picker appears if `playwright` loaded.
   - `mcp__powerbi__model_operations` with a list-only payload → confirms
     `powerbi` loaded (only relevant if scenario uses `/powerbi-model-edit`).

   If any smoke check returns "tool not available", the corresponding
   `.mcp.json` entry needs review (wrong path, missing prereq, etc.).
   Walk the operator back through the relevant `_setup_*_prereq` note.

6. **Log the discovery** — append `MCP-SMOKE | - | - : <pass-count>/<wired> servers loaded | <ok|partial|fail>` to the project `ops.log`.

7. **Sanity-check for unexpected surfaces** — if the deferred-tool list shows
   servers you did **not** wire (e.g. `databricks`, `databricks-sandbox`,
   `ade-core`, or a `vercel` plugin), those are **not** from this repo — they
   are managed-account connectors / user plugins. They inflate every session.
   Point the operator at [`core/conventions/lean-seat-loadout.md`](../../core/conventions/lean-seat-loadout.md)
   for the diagnostic (which layer owns each) and the lever (admin console for
   managed connectors, `/plugin` to disable `vercel`).

This step is recommended but not blocking — operators who explicitly
want REST-only operation (no MCP) can skip it.

### Step 4 — Feedback prompt (first run only)

If this is a first run, after the user has had time to follow the quickstart (return-trip), prompt:

> Did the onboarding work end-to-end? What was confusing? What was missing?

Route the structured response to `/ops-feedback` (Claude Code users) or to a GitHub Issue using the `feedback.yml` template (non-Claude users).

### Step 4.5 — Choose an operating mode (hand-off)

Onboarding ends by making the operating mode an **explicit choice** — don't leave the operator in bare mode without saying so. Surface:

> You're set up. How do you want to operate from here?
> - `/ops-dev` — development on dev/cert (push allowed there, gated)
> - `/ops-operator` — autopilot for routine ops
> - `/ops-prod` — production: read + cert→prod promotion, double-confirmed
> - `/ops-review` — read-only review
> - or stay in **bare mode** (no role gates) — fine for exploring, but log to `ops.log` as `claude-adhoc`, never as a persona you are not operating as.
>
> Pick one to load its gates + logging, or continue in bare mode deliberately.

This is the difference between *operating ade-ops* and *plain Claude calling a few skills*: the personas carry the safety gates and the honest `ops.log` slug (see [`core/conventions/ops-log.md`](../../core/conventions/ops-log.md)).

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
