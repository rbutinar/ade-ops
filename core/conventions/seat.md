# Seat — clone identity convention

> Documentation of the **seat** concept: what it is, how it is registered,
> and how the framework uses seat identity for feedback attribution,
> skill-promotion criteria, and contribution governance.
>
> Maintained by the framework manager. First documented: 2026-05-27.

## What a seat is

A **seat** is one *(clone, distribution)* pair. Concretely: one local
checkout of the ade-ops repository, exercising **one** distribution. A
seat does not migrate across distributions over its lifetime — to
exercise a second distribution you create a second seat (= a second
clone or worktree).

A seat is the unit of *identity* with which the framework reasons about:

- **Who validated what** — skill-promotion criteria such as "1+ non-author
  seat has used this skill without coaching" are scored per seat
- **Where feedback originates** — `/ops-feedback` reports and GitHub
  Issues are tagged with the originating seat name
- **What this clone is allowed to do** — the `roles` field on the
  manifest declares whether the seat may commit directly or must use
  pull requests (see *Governance* below)

The seat name is conventionally the basename of the clone path
(e.g. a clone at `<dev-root>/ade-ops-2` → seat name `ade-ops-2`).
Operators may override with an explicit name in the manifest.

## Manifest schema

The manifest lives at `distributions/<dist>/.seat.yaml`. It is
**gitignored** — it carries personal identifiers (email, tenant IDs)
and is per-clone, not per-distribution. The manifest is created by
`/ade-ops-onboarding` on first run or authored manually.

```yaml
seat:
  name: ade-ops-2                          # conventionally basename of clone path
  created: 2026-05-27                      # ISO date, set on first manifest write
  roles:                                   # see "Roles" below
    - maintainer
    - primary-tester
    - contributor
  distribution: reference                  # the one distribution this seat exercises
  identities:
    databricks:
      email: user@example.com              # workspace user identity
      host: https://<ws>.cloud.databricks.com
    fabric:
      tenant_id: <tenant-uuid>
      identity: <upn-or-spn>               # the principal that az login resolves
  feedback_loop:
    channel: <free-text>                   # e.g. "PR + ops-feedback files"
    cadence: <free-text>                   # e.g. "on-demand", "weekly recap"
```

Operators may add free-form keys under `seat.notes:` for site-specific
context. The engine treats unknown top-level keys as a soft warning, not
a hard error.

## Roles

| Role | Default capability | How it is enforced |
|---|---|---|
| `maintainer` | May commit directly to `main`; may bypass branch protection if admin | Honor-system at the soft layer (the role declaration is visible in the manifest); GitHub admin role at the hard layer |
| `primary-tester` | Exercises Tracks end-to-end; dogfoods `preview` skills; first to surface findings | None — informational role used in feedback attribution and skill-promotion criteria |
| `contributor` | Submits changes via pull request only — no direct commits | Soft layer: declaration; Hard layer: no write permission on repo (fork+PR flow), or branch protection requiring PR review |
| `observer` | Read-only — runs `status`, `diff`, `pull`; never `push` | Honor-system in the engine; could be enforced by Databricks/Fabric workspace permissions |
| `onboarding-canary` | Re-validates the first-arrival experience by resetting to zero state before each test cycle. Read-only by intent (does not promote findings to lab; emits them via `/ops-feedback` like any external operator) | Soft layer: declaration; operational layer: paired with the `scripts/factory-reset.ps1` (soft) or `scripts/fresh-install.ps1` (hard) before each cycle. Operator skills detect the role and tag their `ops.log` entries to keep canary runs separable from real operations |

A seat may hold multiple roles. The most-permissive role wins for
capability checks (e.g. `[contributor, maintainer]` → maintainer
capabilities apply). Exception: `onboarding-canary` is **not stacked**
with other roles — a canary seat is single-purpose by intent and
should not also act as maintainer or contributor.

## How roles affect operator skill behaviour

Operator skills (`/ops-dev`, `/ops-prod`, `/ops-review`,
`/ade-ops-onboarding`) read the `.seat.yaml` `roles` field at boot
(Seat Triad Step 2.5) and adjust their behaviour:

| Role | `/ops-dev` | `/ops-prod` | `/ops-review` | `/ade-ops-onboarding` |
|---|---|---|---|---|
| `maintainer` | full capability, can commit + push | requires explicit confirmation per write to PROD | normal read-only role | acts as full operator |
| `primary-tester` | full capability, may push to DEV with confirmation | refused (PROD requires maintainer) | normal read-only role | acts as full operator |
| `contributor` | refused commits, suggests PR workflow | refused | normal read-only role | acts as full operator |
| `observer` | read-only, refuses push | refused | full read-only role | acts as full operator |
| `onboarding-canary` | acts as if first run; expects no `.seat.yaml` history; suggests `/ops-feedback` for findings | refused (canary is not a production role) | refused (canary is for onboarding, not auditing) | **default home skill** — exercises the entire scenario-picker flow as if fresh |

When the role is `onboarding-canary`, **every ops.log entry written by
the seat is tagged `canary=true` in the detail field**. This lets the
framework manager scan `ops.log` and separate canary signal from real
operations during dogfooding analysis.

## Governance — default rule: PR-only

The default expectation is that a seat **opens pull requests** against
the framework, rather than committing directly. The framework manager
reviews the PR, gauges impact across other seats / distributions, and
merges or requests changes.

Two layers enforce this:

- **Soft layer (this convention)**: the `roles` field on the manifest
  declares intent. A seat tagged `contributor` (without `maintainer`)
  is expected to use PRs.
- **Hard layer (GitHub)**: branch protection rules on `main` requiring
  PR review before merge. For external contributors, the absence of
  write permission on the upstream repo enforces fork+PR.

Exception: a seat with `roles: [maintainer]` may commit directly. This
is intentional — the framework manager is one human who needs
override capability for hotfixes and merge conflicts. For pure
honor-system enforcement, optionally add a `pre-push` Git hook that
warns on direct push to `main`.

## Lifecycle

1. **Creation** — `/ade-ops-onboarding` (F2+) or manual authoring writes
   `distributions/<dist>/.seat.yaml`. The skill prompts for name (default
   from clone basename), roles, distribution slug, and identities. The
   identities can be sourced from existing env vars (`DATABRICKS_HOST`,
   `FABRIC_TENANT_ID`) and `az account show`.

2. **Validation** — subsequent skill invocations (`preflight`, `pull`,
   `push`, feedback skills) read the manifest to attribute actions to
   the seat. Missing manifest is a soft warning, not a hard failure.

3. **Update** — operators may freely edit the manifest as roles or
   identities change. Updates are *not* tracked in git history (the
   manifest is gitignored).

4. **Decommissioning** — a seat is decommissioned by deleting its clone
   directory. There is no central registry to update; the framework
   manager retires the seat name from feedback attribution when
   notified.

## Anti-goals

- **No central seat registry** in the framework repo. Each seat is
  self-described by its local manifest. Identities should not be
  consolidated into a single committed list — that re-introduces the
  leakage pattern the `_private_sanitization_values.yaml` split was
  designed to avoid.

- **No multi-distribution seats**. If you find yourself wanting one
  seat to exercise both `reference` and `<custom>` distributions,
  create a second clone instead. The 1:1 invariant keeps feedback
  attribution and identity boundaries clean.

- **No automatic role escalation**. A `contributor` seat does not
  upgrade to `maintainer` based on activity volume. Role changes are
  explicit edits to the manifest, ratified by the framework manager.
