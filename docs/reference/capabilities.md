# Capabilities & tiers

ade-ops comes in two tiers. The **Community** tier is open source and complete
for single-operator, project-scale work. The **Enterprise** tier adds the
coordination, governance, and managed-distribution capabilities that
multi-operator teams and large governance-heavy programs need.

## Community (open source) — what you get today

A complete, runnable framework, oriented to simple, single-operator use:

| Area | What it does |
|---|---|
| **Scenario-aware onboarding** | Guided setup that routes you to the right starting point (Databricks-only, Databricks → Power BI, or full Databricks → Fabric → Power BI) |
| **Sync engine & state** | `pull` / `push` / `diff` / `status` + preflight; overlay-based multi-environment assembly (DEV / CERT / PROD) with confirm-before-write safety |
| **Operating personas** | Role sessions for developing, operating, promoting to production, and review — human-in-the-loop, not silent autopilot |
| **Databricks operations** | Status, SQL query, notebook/job run, ad-hoc deploy, job & notebook lineage — over REST (MCP-enhanced when available) |
| **Fabric operations** | Notebook / pipeline / SQL / stored-proc / warehouse deploy + run, workspace & lakehouse provisioning, metadata & lineage extraction |
| **Power BI authoring** | Semantic-model scaffolding (Import & DirectLake), live edits, publish, and PBIR report build / clone / extend |
| **Migration assessment** | Databricks → Fabric assessment and execution |
| **Reference scenarios** | Three runnable end-to-end projects on synthetic data — a ~5-minute Databricks-only playground, a Databricks → Power BI (Import) project, and a full Databricks → Fabric → DirectLake chain |
| **Feedback channel** | Structured feedback that adapts to your access (opens an issue on a read-only clone) |

Each capability carries a **maturity marker** (`stable` / `preview` /
`experimental`) so you always know how much to trust a given path. The Community
tier is a curated **subset** of the framework — nothing experimental or
team-scale reaches it by default.

## Enterprise — what the managed tier adds

For teams running ade-ops at scale (multiple operators, shared environments,
governance requirements):

| Capability | What it adds |
|---|---|
| **Multi-operator coordination** | A rich local steward for teams sharing environments — presence, hand-offs, session lifecycle across operators |
| **Real-time fleet awareness** | Live presence + messaging across operator sessions and machines, with targeted alerts when work collides on a shared, production-bound object |
| **Project management & cadence** | A lightweight ticketing + activity model from intake to delivery and post-release iteration, plus periodic status digests |
| **Managed publishing** | A sanitizing publish pipeline that curates exactly what reaches each channel, with leak protection against IP/credential contamination |
| **Curated distribution baseline** | A governed baseline that seeds new team environments with naming conventions, guardrails, real-config handling, identity isolation, and a CI/DevOps mirror |

These are deployed and curated per-team rather than shipped open, so each program
gets the conventions, identity isolation, and audit trail appropriate to its
governance posture.

## The two shapes, side by side

| | **Community** (open source) | **Enterprise** (managed) |
|---|---|---|
| Audience | Individual practitioners, small teams, contributors | Multi-operator teams, governance-heavy programs |
| Scope | Single-operator, project-scale | Team-scale, multi-environment |
| Coordination | — | Real-time fleet + multi-operator steward |
| Governance | Local audit log | PM/cadence, managed distribution, identity isolation, DevOps mirror |
| Support | Community (issues / discussions) | Managed by a framework operator |

## Getting started / inquiring

- **Community**: clone the repository and run the
  [onboarding](../getting-started/) — it takes you from a fresh machine to your
  first operation.
- **Enterprise**: open an issue tagged `enterprise-inquiry`, or reach the
  maintainer, to discuss a managed deployment.

> The maturity of individual capabilities evolves — the [README](https://github.com/rbutinar/ade-ops/blob/main/README.md)
> and the [roadmap](https://github.com/rbutinar/ade-ops/blob/main/ROADMAP.md) are the live source for what's available
> right now.
