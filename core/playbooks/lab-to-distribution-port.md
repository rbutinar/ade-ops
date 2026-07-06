---
status: preview
since: 2026-06-24
related: ops-port-back, build-verify-run-delegate, topology-model
---

# Lab → distribution port discipline

**When to invoke**: porting lab `core/` (framework code) into a distribution that
lives in a **disjoint git world** — e.g. a client's DevOps branch reached through
a bridge clone. lab→distribution is a **manual one-way sanitizing PORT**,
not a git sync (see `topology-model`), so nothing propagates unless someone ports it.

**Why this exists**: because it's manual + per-feature, un-ported `core/` accumulates
**silently**, and a *partial* port breaks the distribution. TICK-042 had to clean up
months of drift by hand, and a partial port (re-syncing `operations.py` without its
`overlay.py` companion) shipped a `TypeError` to the seat. This playbook makes a port
deliberate, companion-complete, and validated.

## The discipline

1. **Run the divergence-report first.** `python tools/core_divergence.py
   --target-repo <bridge-clone> --ref origin/<branch>`. It buckets every `core/`
   file: **DIFFER** (reconcile candidate), **LAB-ONLY** (NEVER-PORT / DISTRO-SCOPED /
   REVIEW), **TARGET-ONLY** (stale/cleanup). It is the cure for silent drift — what
   you don't measure, you don't port.

2. **Classify each DIFFER file before touching it.**
   - *Pure-core, lab-newer, zero client content* → re-sync wholesale.
   - *Has genuine distribution-specific content* → patch **surgically**, preserve it.
   - The report's symbol summary tells **additive** (only `+` symbols → safe) from an
     **interface change** (`-`/renamed symbols → its callers must be ported too).
   - **Eyeball the token flags** — a substring scan lies: a short client slug
     can match inside an unrelated identifier (a 3-letter slug buried in a
     longer library name). A hit is a "read this file", not "it's customized".

3. **Reconcile interdependent engine files TOGETHER.** A call-site needs its callee's
   change. `operations.py` calling `assemble_scope(apply_excludes=…)` is broken until
   `overlay.py` (which defines the parameter) is ported in the same batch. Map the
   companions (`operations`↔`overlay`↔`config`↔`connectors`) before pushing.

4. **Validate with a REAL op, never just an import.** `import core.cli.main` passes
   while a signature mismatch waits to fire on first use. Run an actual
   `diff` / `push --dry-run` / `pull` / `preflight` against a real project in the
   worktree. The TICK-042 regression survived an import check and died on the first
   real `diff`.

5. **NEVER port the security-lab-only set.** `conventions/_private_sanitization_values.yaml`
   and anything that would leak client/private values. The report marks these NEVER-PORT.

6. **Mechanics — isolated, FF, verified, zero-residue.** Port from a fresh worktree off
   `origin/<branch>` in the bridge clone (never the bridge's live working tree). Commit
   with the distribution's trailer convention (`Harness: ade-ops` for a maintainer
   propagation). **Fetch right before push** (active peers on a shared trunk). FF push,
   then **server-verify** the ref. Remove the worktree + temp branch.

7. **Heads-up for behavior changes.** A guard that blocks a daily op (e.g. the
   git-freshness preflight) rolls out **with a team heads-up, not silently** — the
   operator must know what now aborts and how to override (cf. TICK-027 ACT-005).

## The three classes (what the report encodes)

| Class | Meaning | Action |
|---|---|---|
| **Reconcile** | genuine drift in code the distribution uses | port (companion-complete + real-op validated) |
| **Distribution-scoped** | a feature distributions opt into per-need (decks, pm, publish, migration, fabric managers) | leave; port only if the distribution adopts it |
| **Security-never-port** | sanitization values, private payload | never leaves the lab |

A clean run = DIFFER holds only intentional sanitization differences; everything else is
classified and decided. Residual DIFFER is **visible drift to decide on**, not silent.
