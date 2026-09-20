# Enterprise leak boundary — the second boundary (private-but-cross-client)

> **Authoritative.** When the lab seeds or updates a client farm from the
> enterprise baseline, this doc defines what may cross and in which direction.
> The enforcement lives in `core/engine/publish.py` (the `PublishProfile`
> curation knobs + the profile-independent BLOCK pass); this doc is the *why*
> and the *rule*, the code is the *how*.
>
> Complements [`topology-model.md`](./topology-model.md) (repo types + flows)
> and [`distribution-layout.md`](./distribution-layout.md) (where artifacts
> live per distribution). Origin: TICK-036 ACT-002 (2026-06-09 decision).

## Why this exists

ade-ops has **two** leak boundaries, not one:

| Boundary | Trigger | What must not cross | Enforcement |
|---|---|---|---|
| **Public** (existing) | `/ops-publish` → `rbutinar/ade-ops` | client data **and** lab-internal IP — the target is untrusted | sanitize (BLOCK/REPLACE) + curation holds + orphan force-push |
| **Enterprise** (this doc) | seed/update a client farm from the enterprise baseline | **one client's data into another client's farm** — the target is trusted but *cross-client* | the **same** BLOCK pass (cross-client literals refused) + a one-way flow rule |

The public boundary is about *trust* (everything ships to a stranger gets
sanitized). The enterprise boundary is about *isolation between trusted peers*:
every client farm is entitled to the framework, but **one client's data must
never leak into another client's farm**. The baseline is the shared parent; the
farms are siblings that never see each other.

> This very doc is the example: it ships to the enterprise baseline, so it must
> carry **no client literal**. (The first dry-run BLOCKed an earlier draft that
> named a client — the gate below working on its own author.)

## The rule

1. **baseline → farm is ONE direction only.** A farm is *seeded* and *updated*
   from the enterprise baseline. The same one-way discipline the lab already
   uses for its established client farm: the farm evolves in its own git (its
   DevOps repo), the baseline never pulls a farm's working state back wholesale.

2. **farm → baseline port-back is SANITIZED.** When a *generic* improvement is
   discovered in a farm (a connector fix, a convention, a playbook), only the
   **generic** rises — never client data, names, hosts, tenant ids, workspace
   ids, or paths. This is the existing `ops-port-back` discipline generalized:
   the thing that rises must be true for *every* farm, stripped of the one it
   came from. If it carries a client literal, it is not yet baseline material.

3. **Real values live in the farm repo, never in the lab/baseline.** The
   established client farm already works this way — real host/tenant live in its
   own (DevOps) repo, the lab keeps sanitized placeholders (see
   [`seat-isolation.md`](./seat-isolation.md)). A farm gets its real values at
   seed time, in its own repo. The lab's `_private_sanitization_values.yaml`
   BLOCK-lists every *other* client's literals so they cannot ride a seed.

## How the engine enforces it

`core/engine/publish.py` makes the boundary structural, not eyeball-only:

- **Security floor is invariant across profiles.** `PublishProfile.lab_only_path_globs`
  is the same set for `PUBLIC`, `ENTERPRISE_BASE`, and every farm. A profile may
  relax *curation* (what is appropriate/ready for an audience); it can never
  relax the floor that protects secrets (`credentials.yaml`, agent memory,
  `tools/`, `state/`, …).
- **The BLOCK pass is profile-independent.** `publish()` runs the same
  BLOCK/REPLACE/ALLOW rules regardless of profile. The cross-client literals
  (another client's host/tenant/paths) are BLOCK patterns, so an attempt to
  seed a farm with a doc that still mentions another client **aborts loudly**
  with the violation list. The boundary is a hard gate, not a convention you
  remember to follow.
- **The cross-client skill deny is in the profile.** A farm profile's
  `deny_skill_prefixes` includes every *other* client's skill prefix, so
  another client's persona skills can never ship into this farm.
  Engine-enforced, not curated by hand.
- **The core-hold is curation, NOT security.** `PublishProfile.core_hold_globs`
  (e.g. client-laden ops docs held until genericized) is a *readiness* hold. The
  safety guarantee is the floor + the BLOCK pass above it; the hold just keeps
  not-yet-generic content out until ACT-005 cleans it.

## Three faces of one `core/`

The boundary follows from the channel model (see
[`topology-model.md`](./topology-model.md) and the `ade-ops-repo-model` memory):

- **PUBLIC** — `reference`/`demo` → `rbutinar/ade-ops`, sanitized + onboarding-polished.
- **ENTERPRISE** — the baseline → `ade-ops-enterprise`, seeds client farms; keeps
  internal skills + operational conventions, drops lab-meta + public-polish +
  **all** client-specifics.
- **LAB meta** — marketing, ops-publish, lab PM, experiments. Neither face ships these.

A client farm = **enterprise baseline + client-delta − every-other-client**. The
subtraction is this boundary.

## Maintenance

- When a new client farm is added, add its skill prefix to the **other** farms'
  `deny_skill_prefixes` (and add its real literals to the BLOCK list once it has
  any) — the isolation is pairwise.
- Keep `core_hold_globs` shrinking as ACT-005 genericizes the corporate-env
  delta: a doc leaves the hold only when it carries no client literal (verify
  with a dry-run — the BLOCK pass is the proof).
- This boundary is enforced at *seed/propagate* time. The farm's own
  development inside its repo is the farm's concern, not the baseline's.
