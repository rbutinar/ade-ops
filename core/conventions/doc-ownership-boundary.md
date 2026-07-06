# Doc ownership across the lab↔distribution boundary

> **Authoritative. Status: preview** (new 2026-06-18, ratified by a live lab↔seat
> consultation). Where a module's design knowledge lives, and the rule that a doc
> citation must resolve inside its own git-world. Builds on
> [`knowledge-base.md`](./knowledge-base.md) (the KB methodology) and
> [`topology-model.md`](./topology-model.md) (repos & flows).

## TL;DR — the decision

| Question | Answer |
|---|---|
| Where does a **module's** design / "why" live? | In the **distribution** (the delivery repo): the module **README** (the "how/why", code-adjacent) + a **KB entry** under `docs/knowledge/` (durable "what/why/model", freshness-governed). **Never** the framework lab `docs/`. |
| What does the lab `docs/` hold? | **Framework** design only (e.g. `docs/design.md`). Not client/module content. |
| A module file needs to cite a design doc — what may it cite? | Only an artifact that **exists in the same repo** (same git-world). A path that lives only in another repo is **forbidden** — it can never resolve in the reader's clone. |
| A KB entry's `file_refs` may anchor… | …**only** the code that entry actually describes. Never a different module's files. |

## 1. Ownership — module knowledge is distribution-owned

A `{distro}` module's design and rationale belong to the **distribution**, not the
framework core. Two homes, by content type:

- **README** (in the module dir) — the code-adjacent "how it works / how to run it"
  and the "why" that lives next to the code. **Fresh by construction**: it ships and
  versions with the code, so it cannot silently drift from a separate location.
- **KB entry** (`docs/knowledge/<slug>.md`) — the durable "what / why / model /
  contract" you cannot cheaply reconstruct by reading the code, **freshness-governed**
  via `file_refs` (see [`knowledge-base.md`](./knowledge-base.md)).

The framework lab `docs/` is reserved for **framework** design (the engine, the
operating model, conventions). Client/module design placed there is a layering
violation: it couples a `{client}` to the framework and (per rule 3) cannot even be
cited from the distribution repo.

## 2. Scoped `file_refs` — anchor only what the entry describes

A KB entry's `file_refs` are its **freshness anchor**: the entry turns `stale` when
those files change after its `last_verified`. So an entry must `file_ref` **only the
code it actually describes**.

- ❌ Attaching module-B's files to a module-A entry → **scope-pollution**: the entry
  now flags `stale` on churn it doesn't cover (**false-stale**), and its subject blurs.
- ✅ If module-B's knowledge needs an anchor, it gets its **own** entry — or none, if a
  README + docstrings already cover it (don't mint an entry for its own sake).

A `file_ref` is a claim: *"this entry describes this code."* Keep the claim true.

## 3. A citation must resolve in its own git-world

The framework lab and a distribution's delivery repo are **disjoint git-worlds — no
shared history** (see [`topology-model.md`](./topology-model.md): the *maintainer lab*
and the *team repo* are different repositories; an operator clones the **distribution**
repo, not the lab).

Consequence: a file in the distribution repo that cites a path living **only** in the
lab (e.g. a lab-only `docs/…` doc) is **structurally broken** — that path does not
exist in the operator's clone and can never resolve. This is not a "fix the link"
problem; the reference is **impossible** by construction.

**Rule:** every doc citation must point at an artifact present in the **same repo** as
the file doing the citing. Cross-git-world doc citations are forbidden. (The same logic
forbids the reverse: framework files must not cite distribution-only paths.)

## Remediation — a dangling design-doc citation

When code or a README cites a design doc that **does not exist in this repo** (the
classic symptom of a cross-boundary or deleted doc), do **not**:

- ❌ **Port** the doc into the framework lab — that puts module content in the framework
  (rule 1) and still can't be cited across the boundary (rule 3).
- ❌ **Reconstruct** it as a standalone static doc — recreates stale-blindness and
  **duplicates** the KB entry that should own the "why" → two sources that drift.
- ❌ **Mint a KB entry** when the README + code docstrings already carry the content —
  don't manufacture an anchor for its own sake.

Instead — **repoint to same-repo artifacts**:

1. Map each cited section to where its content actually lives **in this repo**:
   - "how it works / how to run" → the module **README** (cite `README.md (§X)`).
   - "what / why / model / contract" → the **KB entry** (link it; don't copy).
2. **Reconstruct only the true residue** — a cited section whose content is in *neither*
   the README, nor the KB entry, nor the code's own docstrings. Write that residue
   **into** the README (how) or the KB entry (why) — **never** resurrect a standalone
   doc to hold it.
3. Often the residue is **~zero**: self-documenting code (docstrings) + README + a
   scoped KB entry already cover it, and the dangling doc simply **dies**.

## Status — promotion to `stable`

- ≥2 distinct dangling-citation / doc-ownership cases resolved with this rule without
  rework.
- One operator other than the author applied the remediation without coaching.
- No case surfaced where a standalone design doc was genuinely the right home (which
  would mean the rule needs a carve-out).
