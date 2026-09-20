---
description: "How ade-ops is built and why it is safe to operate with humans and AI agents together: framework core vs distributions, overlays, and the assembly pipeline."
---

# Architecture & concepts

How ade-ops is built, and the ideas that make it safe to operate by humans and
agents together.

## Core vs distribution

ade-ops has two tiers: a generic **framework core** and per-deployment
**distributions** that build on it. A distribution never modifies the core — it
*consumes* it.

![Core and distributions: a distribution consumes the generic core and never modifies it](../assets/diagrams/core-distributions.svg)

```
ade-ops/
├── core/                              # Generic, client-agnostic
│   ├── engine/                        # config / overlay / state / operations
│   ├── connectors/                    # Databricks, Fabric, Power BI
│   ├── conventions/                   # naming, sanitization, status protocol
│   ├── playbooks/                     # operational patterns
│   └── templates/                     # scaffolding for new projects
│
└── distributions/                     # Per-deployment customization
    └── reference/                     # The public reference implementation
        └── projects/<project>/        # Self-contained: src + overlays + state + config
```

Each **project** under a distribution is self-contained — its own config,
credentials, overlays, and state — so it can be moved or detached independently.

## The assembly pipeline (the contract)

The central idea: you author once in `src/`, and what gets deployed is the
result of layering environment config on top of it.

![The assembly pipeline: src plus overlays plus patches, deployed behind a diff gate](../assets/diagrams/assembly-pipeline.svg)

```
src/ (single source of truth)
  → overlays/{env}.yaml      (catalog/schema remap, text replace, exclusions)
    → patches/{env}/         (temporary env-specific overrides)
      → deployed to the remote
```

- **`src/`** is where you author. It's the canonical version; environment
  differences never live here.
- **`overlays/`** hold declarative, per-environment transforms (which catalog,
  which schema, what to exclude) — not business logic.
- **`patches/`** are temporary per-environment overrides for the rare case an
  overlay can't express.
- **`state/`** mirrors what's actually deployed remotely. It is *pulled*, never
  hand-authored.

## Four operations, one safety rule

| Operation | What it does |
|---|---|
| `pull` | Download remote state → `state/{env}/` |
| `push` | Assemble `src` + overlay + patches → upload to the remote |
| `diff` | Compare assembled local vs pulled state |
| `status` | Overview: last pull, file counts, patch warnings |

**Remote workspaces are authoritative, and every remote write is gated.** Before
any `push`: assemble, show the diff against state, wait for explicit
confirmation, then upload. `pull` / `diff` / `status` are read-only with respect
to the remote.

## The framework admits what it doesn't know

Two conventions keep trust calibrated:

- **Skill maturity.** Every skill carries a `status:` field — `experimental`,
  `preview`, or `stable` — so you (and your agent) know how much to trust a given
  path before running it.
- **Honest converters.** The notebook converters tag their output as `compat`,
  `light`, `heavy`, or `impossible` — the last two are explicitly *your* call,
  not the tool's.

## Two deployment shapes

ade-ops runs in two operational shapes:

- **Community / self-service** (this open-source repo): you clone, run
  onboarding, and operate your own instance. Updates arrive via `git pull` from
  upstream; feedback flows via GitHub Issues and Discussions.
- **Enterprise** (managed, not in this repo): a curated baseline that seeds
  team deployments with naming conventions, guardrails, identity isolation, and a
  CI/DevOps mirror — for multi-operator, governance-heavy teams. See
  [capabilities & tiers](../reference/capabilities.md). If you're investigating an
  enterprise deployment, open an issue tagged `enterprise-inquiry` or reach the
  maintainer.

## Built for humans + agents

ade-ops is usable from a plain CLI (`python -m core.cli …`), and that path is
agent-agnostic. It reaches its potential when paired with an AI coding assistant
that can drive its skills — Claude Code is the optimised path, with Copilot and
Codex supported at the CLI/recipe level. See the root `CLAUDE.md` / `AGENTS.md`
for the assistant conventions.
