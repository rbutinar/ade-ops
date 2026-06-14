# Topology model — repos, flows, identities

> The general operating model that unifies orphan release, the seat
> triad, and inter-agent consultation. Documented 2026-05-28 after
> emerging from the cross-distribution test setup (Roberto + ops-manager).

## Three repository types

| Type | Role | Examples |
|---|---|---|
| **Template repo** | Source from which new seats are bootstrapped. Distributes framework releases. A seat clones from here at "first install". Subject to the orphan release model — history wiped at every release. | `rbutinar/ade-ops` (public preview) |
| **Team repo** | Cross-seat coordination. Hosts long-lived thread files, handoff documents, shared state, audit history for a team running ade-ops together. Adopted by a team when ≥ 2 seats need to coordinate. Standard git semantics — full history, no orphan. | A private Azure DevOps or GitHub Enterprise repo provisioned per team |
| **Maintainer lab** | Canonical source of the framework. Private to the template maintainer. Receives feedback from seats, absorbs into source, releases to the template via `/ops-publish`. Standard git semantics — full history. | `rbutinar/ade-ops-lab` |

A given team may operate with all three (the canonical reference is
an enterprise team: maintainer lab privately maintained by the
framework maintainer, team repo on a private host, public preview as
upstream template), or with a subset (smaller teams may skip the
team repo until 2+ seats emerge).

## Three communication flows

| Direction | What flows | Transport | Example |
|---|---|---|---|
| **Intra-team** (seat ↔ seat within a team) | Consultations, handoffs, dialogue, shared state | Subagent (same session) / thread file (same filesystem or team repo) / handoff committed (any topology) | `team-seat-1` ↔ `team-seat-2` via `<team-repo>/docs/handoffs/` |
| **Seat → Template** (feedback bottom-up) | Bugs, gaps, findings, uncovered scenarios | `/ops-feedback` files / GitHub Issues / advisory PRs against template (commits do not survive next `/ops-publish` under orphan model) | `ade-ops-2` wave 1 findings absorbed into lab `f710c53` |
| **Template → Seat** (update top-down) | Framework releases, new skills, engine fixes, conventions | `/ops-publish` orphan release on template; seat does `git fetch + reset --hard origin/main` | This morning: `b7f2d1d → 17ea076` |

The maintainer lab is **outside** the seat→template loop — it
absorbs feedback and produces releases, but never directly receives
seat traffic. The template is the only public-facing endpoint.

## Three identities a seat knows about itself

Read at boot by every operator skill (`/ops-dev`, `/ops-prod`,
`/ops-review`) in the Seat Triad step. See `core/conventions/seat-triad.md`.

1. **Seat identity** — *who am I?* — from `distributions/<dist>/.seat.yaml`:
   name, role(s), distribution, identities for external platforms.
2. **Distribution identity** — *which distribution am I exercising?* —
   from the path layout (`distributions/<dist>/`) and the `.seat.yaml`
   `distribution:` field.
3. **Topology identity** — *what type of repo am I living in?* —
   inferred from `git remote -v` + presence/absence of marker files:
   - `docs/handoffs/` populated → likely team repo or maintainer lab
   - Orphan history pattern (single commit, message `Release ...`) → template clone
   - Multi-distribution under `distributions/` + lab-only paths
     (`docs/feedback/`, `docs/backlog/`, `.claude/agents/_threads/`)
     present → maintainer lab

Knowing all three, the seat can answer:

- *Can I commit directly to main?* → topology + seat role decide.
  Maintainer lab + maintainer role → yes. Team repo + maintainer role
  → yes (with policy). Template + any role → no, only advisory PR
  (does not survive next release).
- *Can I use handoff?* → only if topology supports persistent commits.
  Team repo or maintainer lab: yes. Template: no — orphan wipes them.
- *Where do I receive updates from?* → always the template the seat
  was bootstrapped from. Unless this seat IS the maintainer lab.
- *Where do I send feedback to?* → toward the template the seat
  consumes. Transport varies: GitHub Issue (if template is public),
  `/ops-feedback` file (if template has the engine), PR (advisory).

## Bootstrap patterns — how a new seat is born

A new seat comes into existence in one of two ways:

1. **From a template repo** — fresh clone of an ade-ops release, zero
   prior state. The seat creates its own `.seat.yaml`, sets identities,
   may run `/ade-ops-onboarding` to configure the first distribution.
   This is the "blank install" path.
2. **From a team repo** — clone of a team repo that already hosts
   other seats. The new seat joins an in-flight orchestration: it
   reads existing handoffs, threads, and shared state. The new seat
   creates its own `.seat.yaml` (the manifest is per-clone — not
   shared across seats in the team repo) but inherits the team's
   conventions and pending work.

Historical note: the first ade-ops team adoption (pre-public-preview)
bootstrapped seats directly from a team repo because there was no
public template yet. Subsequent seats joined the in-flight team
setup from the same team repo.

Future external teams will likely bootstrap their first seat from
the **template** (public preview), then set up their own team repo,
then bootstrap subsequent seats from that team repo.

## How an agent self-orients at session start

When `/ops-dev`, `/ops-prod`, `/ops-review`, or any operator skill
starts, it executes the topology-aware boot sequence:

1. **Read identity** (Seat Triad — Identity layer): `.seat.yaml` if
   present, else fall back to clone-path basename.
2. **Read distribution identity**: from layout + manifest.
3. **Read topology identity**: from `git remote -v` + marker files.
4. **Read context** (Seat Triad — Context layer): last session log if
   present.
5. **Read ops** (Seat Triad — Ops layer): tail of `ops.log`.
6. **Self-position**: derive capabilities (commit? handoff? feedback
   transport?) from topology + role.
7. **Surface a briefing** to the operator: "Seat X on topology Y in
   distribution Z. Last session …; open findings …; capability …".

This makes every agent **location-aware** without the operator
having to brief it manually.

## Communication setup — how an agent guides cross-seat dialogue

When an agent receives a request to coordinate with another seat,
the host skill (or `core/playbooks/inter-agent-consultation.md`)
walks the operator through the decision tree:

1. **Same machine, same session** → subagent spawn (Agent tool)
2. **Same machine, same repo** → native thread file
   (`.claude/agents/_threads/`)
3. **Same machine, different repos** → external shared path
   (`&lt;dev-root&gt;/_shared_threads/`)
4. **Different machines, same team** → team-repo handoff
   (`<team-repo>/docs/handoffs/` or `<team-repo>/docs/threads/`)
5. **Different machines, no team repo** → set up a team repo first
   (or fall back to manual relay through the human)

See `core/playbooks/inter-agent-consultation.md` Step 0.5 for the
expanded decision tree.

## Governance — who decides what, and where it can move

The three repo types describe *where code lives*. Orthogonal is *who has
authority over a decision*. Today this is **two real tiers plus a triage
rule** — not a three-level org chart:

- **Lab `ops-manager`** (framework constitution) — real skill
  (`.claude/commands/ops-manager.md` + agent memory). Owns engine,
  conventions, propagation rules for ALL distributions.
- **Seat steward** (`ops-local-manager` / `seat`) — real skill. Owns a
  single clone: onboarding, reconciliation, per-user memory.
- **Blast-radius triage** — NOT a persona; a *responsibility* the lab
  `ops-manager` already carries, codified in
  [`distribution-evolution.md`](./distribution-evolution.md) ("decide
  whether a fix is team-scoped, distribution-scoped, or
  framework-scoped"). Route by reach: one clone → seat steward; one
  farm (all its seats + platform bindings + deliverable repo) → lab
  `ops-manager` reaching across; all distributions → lab `ops-manager`
  as framework owner.

There is deliberately **no distribution-resident governance persona
today**. Farm-wide matters (repo topology, branch layout, platform
bindings) are decided by the lab `ops-manager` reaching into the
distribution, while the seat steward does read-only investigation and
parks findings. This is normal *today*, not a smell — it is exactly the
`distribution-evolution.md` triage — and it works while one operator
drives both and the distribution is not sovereign.

### Trajectory — when governance migrates to the periphery

Authority *can* move outward, and `distribution-evolution.md` already
sets the trigger: a **Pattern B/C fork that stops following the lab
upstream** and maintains its own framework fork has, by definition,
taken framework authority local. At that point the distribution needs
its **own** governance owner — an elevation of a seat's authority, or a
thin distribution-resident manager — and the lab degrades from
*governor* to *optional upstream* (the farm may pull its rules or ignore
them). The distinction is between *consuming the rules* and *being
governed by them*.

This role is **not instantiated**, and is intentionally **left unnamed
here**: "distribution-level" is already taken (`ops-local-manager`'s
entry point; operative skills in `project-recap-protocol.md`), so a
distinct name is chosen *when* the role is built — not pre-coined. Until
a farm actually goes sovereign, do not create it (CLAUDE.md: "solve the
current problem, don't build for hypothetical futures"). The reaching-
across pattern becomes a smell *only after* a distribution has gone
sovereign and the lab keeps deciding for it anyway.

## Anti-patterns

- **Public template as handoff transport** — orphan release wipes
  handoffs. Use team repo or maintainer lab.
- **Deciding a farm-wide matter at the seat-steward tier** — repo
  topology, branch renames, platform bindings span all seats of a farm;
  the seat steward investigates read-only and parks findings, but the
  decision sits with the lab `ops-manager` (blast-radius triage), not
  `ops-local-manager`.
- **Maintainer lab as team repo** — the lab is single-maintainer by
  design; multi-author handoffs there confuse audit. Set up a team
  repo for multi-author work.
- **Feedback direct to maintainer lab** — the lab is not publicly
  reachable. Feedback transits through the template's public
  interface (Issues, advisory PRs, `/ops-feedback` files in cloned
  template).

## Why this matters

Without this model, an agent in a new seat would have to discover
its environment empirically: "can I push? can I open a PR? where do
handoffs go? who do I report bugs to?". The discovery is error-prone
and per-agent.

With this model, **every agent knows the same map**. Asking
"how does ade-ops coordinate cross-seat?" yields one canonical answer
(this document + the playbooks it references) regardless of where
the agent lives. The operator's question collapses to "what do you
want to do?" — the agent figures out the right transport from
topology + capability.

## Related

- [`seat.md`](./seat.md) — formal seat schema (the *(clone, distribution)* pair)
- [`seat-triad.md`](./seat-triad.md) — identity/context/ops layers per seat
- [`../playbooks/inter-agent-consultation.md`](../playbooks/inter-agent-consultation.md) — cross-agent dialogue with topology decision tree
- [`../../.claude/commands/ops-publish.md`](../../.claude/commands/ops-publish.md) — orphan release model on template repo
