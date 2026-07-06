---
description: "From a fresh machine to your first deploy — install and clone ade-ops, then let an AI coding assistant drive onboarding on Databricks, Fabric or Power BI."
---

# Getting started

ade-ops is **agent-driven in two phases**: a small **terminal bootstrap** (install
+ clone + launch), then **onboarding and operations driven by an AI coding
assistant** (Claude Code is the optimised path; the CLI is agent-agnostic). This
page takes you from a fresh machine to your first operation.

## Prerequisites

- **Python 3.10+**
- **Git**
- **Node.js LTS** — for Claude Code (the agent that drives onboarding and the skills)
- **A Databricks workspace** (Community Edition works for the sandbox case)
- *Optional:* a **Microsoft Fabric** workspace + **Power BI** Pro/Premium

## Phase 0 — Bootstrap (terminal)

```bash
git clone https://github.com/rbutinar/ade-ops.git
cd ade-ops
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

Then install the agent and launch it from inside the repo:

```bash
npm i -g @anthropic-ai/claude-code   # needs Node.js LTS
claude                               # authenticate on first run; run it from the repo dir
```

> Optional but recommended: install **Claude Desktop** — once setup is done it's
> the nicer home for ongoing work (reading notebooks, diffs, reports). Onboarding
> itself is smoothest continued right here in the terminal CLI you just launched.

## Phase 1 — Onboarding (agent-driven)

Inside the Claude Code session you just launched, the canonical entry point is:

```
/ade-ops-onboarding
```

It asks which scenario fits your environment and routes you to the matching
quickstart:

| Scenario | When to pick it |
|---|---|
| **`databricks-only`** | Only Databricks, no Fabric/Power BI yet — notebook + job deployment per environment. The fastest start. |
| **`databricks-to-powerbi`** | Databricks + Power BI (Pro/Premium) — notebooks + PBIR reports + semantic models, Import mode (no Fabric capacity needed). |
| **`databricks-to-fabric`** | Databricks + Microsoft Fabric — the full medallion → Fabric lakehouse → DirectLake semantic model → Power BI chain. |

All scenarios are **BYO**: you bring your workspace, your notebooks, and your
identity; ade-ops scaffolds the workflow. The per-scenario manual steps are under
[`docs/quickstart/`](../quickstart/).

> In the current preview the onboarding skill routes and explains; it does not
> yet auto-scaffold or wire identity for you — those steps live in the quickstart.

## Credentials — never in chat

Secrets (tokens, PATs) go into a **gitignored** `config/credentials.yaml` via an
editor, **never typed into the agent chat** (transcript/log exposure). Onboarding
pauses and tells you to paste the token into the file rather than asking for it.

## Verify the setup

Once a scenario is scaffolded, run preflight against the new project:

```bash
python -m core.cli preflight --project distributions/reference/projects/<your-project-name>
```

You should see green ticks for Python, dependencies, project config, credentials,
and platform reachability. Anything red explains what to set.

## Your first operations

```bash
python -m core.cli status                              # env × scope overview
python -m core.cli pull  --env dev --scope notebooks   # remote → local state
python -m core.cli diff  --env dev --scope notebooks   # compare assembled local vs remote
python -m core.cli push  --env dev --scope notebooks --dry-run   # preview the change
python -m core.cli push  --env dev --scope notebooks             # upload (after confirmation)
```

Every write to a remote environment requires explicit confirmation. `pull` /
`diff` / `status` are read-only with respect to the remote — they only write to
local `state/`.

Next: the [guides](../guides/) (task-oriented how-tos) and the
[concepts](../concepts/architecture.md) (how the pieces fit).
