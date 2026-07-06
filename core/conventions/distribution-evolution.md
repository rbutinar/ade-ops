# Distribution evolution — how teams scale, fork, and learn from each other

> Companion to [`topology-model.md`](./topology-model.md): once a team has
> a working ade-ops distribution, how does it scale? This document maps
> the three concrete growth paths and the value each one returns to the
> framework as a whole.

## The question that opens this door

> "Our team needs to onboard new users / projects / partners. Should we
> reuse the existing distribution, fork it, or start over from the
> public template?"

The answer depends on **how much of the existing distribution's
configuration genuinely applies to the new context**. Three answers map
to three patterns.

## The three scaling patterns

### Pattern A — Add a project to the existing distribution

**Trigger**: same team, same conventions, same governance, **new
project scope** (e.g. an existing team already runs one project and
now wants to onboard a second project on the same Databricks workspace).

```
<team>-team-repo/
└── distributions/<team>/
    ├── conventions/          ← unchanged
    ├── roles/                ← unchanged
    ├── presets/              ← unchanged
    └── projects/
        ├── existing-project/
        └── new-project/      ← NEW: add here
```

**Cost**: zero refactor. Add a `projects/<new>/` folder, scaffold via
`/ops-init`, point at the right environments in `project.yaml`.

**Operators**: existing seats (`<team>-seat-1`, `<team>-seat-2`) operate
on any project under the same distribution. No new seat needed unless
team headcount grows.

**Audit**: single team repo, single chain of authorisation, single ops
log per project. Cleanest pattern.

**When NOT to use**: if the new project has materially different
governance (e.g. it's a different LOB with separate compliance
boundary, or it targets a different cloud / tenant) — Pattern B or C
fits better.

### Pattern B — Fork the distribution for an affiliated team

**Trigger**: a different team wants to adopt **most** of your
distribution's conventions (70-90% overlap — same industry, same Power BI
brand style, same platform target) but needs **separate governance**:
their own backlog, their own seats, their own audit trail.

```
<original-team>-team-repo/        <new-team>-team-repo/
└── distributions/<original>/     └── distributions/<new-team>/
    ├── conventions/                  ├── conventions/      ← forked
    ├── roles/                        ├── roles/            ← forked, may diverge
    ├── presets/                      └── projects/
    └── projects/...                      └── primary-project/
```

**Cost**: fork the team repo, rename `distributions/<original>/` →
`distributions/<new-team>/`, decide which conventions to keep vs adapt.
A separate Azure DevOps / GitHub Enterprise repo is provisioned.

**Operators**: separate seat clones for the new team (`<new-team>-seat-1`,
etc.). The framework maintainer (you) tracks both forks.

**Sync**: each fork follows the **lab upstream** (`ade-ops-lab` private)
for framework-level updates. Cross-fork sharing (e.g. a fixture that
both forks find useful) happens via lab port-back: the lab maintainer
absorbs the contribution + the next release ships it to both forks.

**Audit**: two separate audit trails (one per team). No
cross-contamination.

**When NOT to use**: if the new team has < 70% overlap — Pattern C
(start clean) is honest about the divergence.

### Pattern C — Start clean from the public reference

**Trigger**: a team / partner / customer wants ade-ops but their
conventions do not derive from any existing team — different industry,
different compliance, different stack assumptions.

```
public template (rbutinar/ade-ops)
            │
            │ git clone + provision a new team repo
            ▼
<new-team>-team-repo/
└── distributions/<new-team>/
    ├── conventions/   ← from reference distribution, then adapt
    └── projects/
        └── primary-project/
```

**Cost**: identical to setting up the first ade-ops adopter — clone
public preview, scaffold a new distribution, write team-specific
conventions. The framework manager onboards the new team as a fresh
relationship (no shared assumptions with existing forks).

**Audit**: completely separate. The new team operates as an
independent adopter of the public framework, with the same maintainer
relationship the original team had at its inception.

**Trade-off**: the new team does not inherit institutional knowledge
from existing forks. If patterns turn out to be similar after the
fact, lessons learned still flow through the **lab maintainer** as
the central knowledge node.

## Decision tree

```
How much of the existing distribution's setup applies to the new context?

≥ 90% (same team, new project)
  └── Pattern A: add projects/<new>/

70-90% (different team, mostly shared conventions)
  └── Pattern B: fork the team repo, distribute as new distribution

< 70% (different team, different conventions)
  └── Pattern C: start fresh from the public reference template
```

## What each pattern returns to the framework as a whole

Beyond the immediate team need, each scaling pattern produces **a
distinct learning signal** for the framework manager:

| Pattern | Returns to the framework |
|---|---|
| **A (same team, new project)** | Validates that the distribution's conventions are stable enough to be applied to a different project shape. Failures here reveal hidden coupling between conventions and the original project. |
| **B (fork affiliate)** | Validates **distribution mobility** — can the conventions transplant? Each fork-then-diverge cycle teaches which conventions are genuinely framework-level (lab-portable) vs team-specific (should have been distribution-private). |
| **C (start clean)** | Validates the **public reference distribution** as a self-contained adopter starter kit. Friction observed during a Pattern C onboarding is direct feedback for the reference (CHANGELOG entries, README, quickstart docs). |

The framework maintainer learns most from Pattern B and Pattern C
because they exercise the boundary between "framework concern" and
"team concern". Pattern A is comfortable but mostly confirms existing
design.

## Where new users get activated — the "dove li attiviamo" question

When a request comes in to add new users, the location decision follows
from the pattern:

| Pattern | New user activated where |
|---|---|
| **A** | Same team repo. They get added as a contributor + receive their own seat clone. Same identity as existing users. |
| **B** | New team's fork repo. Separate contributor list, separate seats. They never see the original team's projects. |
| **C** | New team's fresh repo. The framework maintainer onboards them as a new adopter (same playbook as the original team's first seat). |

The mistake to avoid: **adding a user from a different organisational
boundary directly to an existing team's repo**. That creates
governance ambiguity (whose policies apply? whose audit trail does the
user touch?). Patterns B and C exist precisely to avoid that.

## How knowledge flows across patterns

The lab `ade-ops-lab` (private to the framework maintainer) is the
**central knowledge node**:

- Pattern A insights stay within the team (they affect the team's
  conventions, not the framework).
- Pattern B insights flow to the lab IF the diverging convention
  proves useful generally → port to framework `core/`.
- Pattern C insights flow to the lab → eventually surface in the next
  public reference release via `/ops-publish`.

The maintainer's role: triage feedback by pattern, decide whether a
fix is team-scoped (apply only to the team's fork), distribution-scoped
(apply to all forks that share the convention), or framework-scoped
(apply to `core/` and propagate to all distributions via the next
release).

## Anti-patterns

- **Mixing patterns mid-stream**: starting as Pattern A and then
  treating it as Pattern B by adding governance-isolated users later.
  The audit trail becomes confused. Decide upfront.
- **Pattern B-then-deviate**: forking a team's repo and immediately
  rewriting most conventions. If the rewrite is > 30%, you were
  always Pattern C — fork the public reference instead.
- **Pattern C without lab access**: spinning up an independent
  adopter without involving the framework maintainer. The team loses
  the upstream release stream — fine if the team is willing to
  maintain its own framework fork, otherwise a slow drift trap.
- **Shared seat across teams**: a single human operating seats for
  two different team repos on the same machine without using the
  modality-3 credentials pattern. Cross-seat leaks (see
  `credentials.md`) become inevitable.

## Related

- [`topology-model.md`](./topology-model.md) — three repo types
  (template / team / maintainer lab), three communication flows
- [`seat-triad.md`](./seat-triad.md) — per-seat user-data partition
  that survives orphan releases
- [`seat.md`](./seat.md) — formal `(clone, distribution)` pair schema
  and the role table that governs each seat's capabilities
- [`credentials.md`](./credentials.md) — cross-seat conflict + DPAPI
  trade-offs that become acute in multi-distribution operator
  environments
