# Lean seat load-out — where context goes at startup, and which levers are yours

A seat session pays a **static context cost at startup**, before any real work: tool
catalogs, skill descriptions, plugin agents, and skill bodies are injected up-front. On one
analytics seat this measured ~85k tokens of startup occupancy (measured 2026-06-05) — most
of it *not* the operator's doing and *not* fixable by editing this repo.

This convention is the **map**: it names every layer that contributes, says **who owns each
lever**, and gives the lean recommended set. Use it when a session feels heavy, or when
`/context` looks small but the model still behaves like it's full (it under-reports — see
below).

## The four layers (and who can prune each)

| Layer | Examples | Where it lives | Who prunes it |
|---|---|---|---|
| **1. Project MCP** | `databricks`, `powerbi`, `playwright` | repo `./.mcp.json` (gitignored; template `.mcp.example.json`) | **You** — edit `.mcp.json`, relaunch |
| **2. User MCP** | `github`, `playwright` | `~/.claude.json` (`mcpServers` + per-project `enabledMcpjsonServers`) | **You** — edit, relaunch |
| **3. Managed-account connectors** | `databricks`, `databricks-sandbox`, `ade`, `ade-core`, `ade-extended`, `mcp-registry`, `scheduled-tasks`, `drawio`, `Claude_in_Chrome`, `Claude_Preview`, `ccd_*` | claude.ai connectors / enterprise admin console (`~/.claude/remote-settings.json` `allowedMcpServers` whitelists, does not *define* them) | **Admin console** — NOT this repo, NOT local files |
| **4. Harness deferred catalog** | the ~250 tool **names** (~67k tokens) injected up-front even though schemas are now deferred | Agent SDK managed layer | **Upstream (Anthropic)** — file it; not framework-fixable |

**Diagnostic — find where a server comes from before trying to prune it:**

```powershell
# layer 1 — this repo
python -c "import json; print(list(json.load(open('.mcp.json'))['mcpServers']))"
# layer 2 — user global + per-project
python -c "import json,os; d=json.load(open(os.path.expanduser('~/.claude.json'))); print('global:', list((d.get('mcpServers') or {}).keys()))"
# layer 3 — if a server is in NEITHER of the above but shows in the deferred-tool list,
#           it is a managed-account connector → claude.ai / admin console, not a local file.
```

> **`/context` under-reports.** After the deferred-tools change, `/context` excludes the
> deferred name catalog — it can read "2%" while true startup occupancy is ~85k. Don't trust
> the headline number when judging bloat; the name catalog (layer 4) is physically in the
> system prompt.

## The triplication (the avoidable part of layer 3)

An analytics seat ends up with **three near-identical Databricks surfaces**
(`databricks`, `databricks-sandbox`, `databricks` — ~50 `manage_*`/`execute_*` tools each) and
**three overlapping ADE surfaces** (`ade` catalog/lineage, `ade-core` redundant,
`ade-extended` live query). For typical work, exactly **one** Databricks server (`databricks`, the
workspace-scoped one) and **`ade` + `ade-extended`** are used. The rest is pure
duplication injected every session.

Because these are **layer 3 (managed-account)**, the fix is an **admin-console action**, not
a repo change: drop `databricks` + `databricks-sandbox` and retire `ade-core` from the
account's enabled connectors for analytics seats. The framework cannot do this for you — it
can only tell you it's the single biggest avoidable line item.

## Recommended lean set, by scenario

The framework wires only **layer 1** (`.mcp.example.json`). Wire only what the scenario uses:

| Scenario | Project MCP needed | Skip |
|---|---|---|
| Databricks-only (build or migrate) | `databricks` | `powerbi`, `playwright` |
| + Power BI / Fabric (report deploy) | `databricks`, `playwright` | `powerbi` (only if `/powerbi-model-edit`) |
| + live semantic-model editing | `databricks`, `powerbi`, `playwright` | — |
| REST-only operation | *(none)* | all — managed skills run over REST from `credentials.yaml` |

Plugins are user-scoped (layer 2-ish): **do not run an analytics seat with `vercel` enabled**
— it injects ~30 skill descriptions + 3 agents for zero relevance. Disable via `/plugin`.

## What the framework owns vs what it doesn't

- **Owns (this repo):** the lean layer-1 template, scenario-conditional wiring in
  `/ade-ops-onboarding`, keeping skill bodies tight, and *this map* so the levers are legible.
- **Does not own:** the managed-account connector set (admin console) and the harness name
  catalog (upstream). When a session is heavy, the framework's honest answer is "here is the
  map and the levers" — not a repo edit that pretends to fix layers 3–4.

Tracked under TICK-021. The harness name-catalog dedup is filed as TICK-021 ACT-003 (upstream,
track-only).
