# Knowledge base — deposited, queryable, freshness-governed

> **Status: experimental** (since 2026-06-07). Lab-first pilot of the KB layer
> (TICK-024 ACT-002). The engine and this convention may change shape between
> sessions. See "Preview tracking — known unknowns" at the end.

## What this is

A place to **deposit** durable knowledge once and **query** it cheaply, instead
of reconstructing it every session from context, memory, or by re-reading the
same notebooks and READMEs. Three problems it targets:

1. **Token waste** — re-reading a notebook + README each session to re-derive
   what a thing is / why it exists.
2. **Stale-blindness** — prose knowledge with no signal for "is this still true?".
3. **Locked-away knowledge** — READMEs excluded from PROD (anti-stale policy), so
   the "why" lives nowhere durable.

It is **not** a vector database and **not** a knowledge graph. See *Retrieval
discipline* — agentic grep stays the default; the index serves only what grep
cannot cheaply reconstruct.

## Content model & governance

**What goes in:** the meta-layer — what / why / meaning / lineage — that you
cannot cheaply reconstruct by grepping the file. **Never a copy of the code or of
an artifact's content** (the code is the code; link it via `file_refs`).

| Subject | NOT in the KB | IN the KB |
|---|---|---|
| Artifacts / domain (notebooks, models, docs) | the artifact's content restated | domain glossary, lineage (who reads/writes what), the operational "why" |
| Harness / framework (engine, conventions — code itself) | code restated | design rationale + cross-file mental models no single file holds; an index + freshness over existing conventions |

Because the harness *is* readable code, agentic grep already covers most of it →
the KB adds little there (only the scattered "why"). The payoff is on **domain
artifacts**, where semantics and lineage are implicit and costly to re-derive.

**Who writes, when:**

| Layer | Who | When | How |
|---|---|---|---|
| SEMANTIC (decisions, glossary, why) | the human/agent who owns that knowledge | at the natural checkpoint (decision made, term clarified, thread closed) | a deliberate act, like writing a ticket/feedback |
| STRUCTURAL (lineage, inventory) | a script/skill (deterministic) | on-demand / after a pull / on a cadence | regenerated; an owner commits the snapshot — never by hand |
| OPERATIONAL (ops.log, playbooks) | operative skills in their flow | during operations | already emergent, already governed |

Cross-cutting: the `stale` check flags entries whose `file_refs` changed after
`last_verified` → a human reviews and refreshes. This is what stops knowledge
rotting silently.

**Additive or replace:**

| Level | Model | Why |
|---|---|---|
| The collection (set of entries) | **ADDITIVE** — new knowledge = a new file | one concept per file → clean git diffs/merges |
| A single entry | **REPLACE in-place** — edit the `.md`, git keeps the history (NOT append inside the file) | an entry states the *current* truth about X, not a diary |
| The jsonl / structural snapshot | **FULL REGENERATE** — rebuilt from scratch, never hand-edited | it is a projection, not a source |

The KB is **current-truth**, not a log. History lives where it already does: git
(entry content) and `ops.log` (operational events). The KB does not duplicate
them — it is the "present", they are the "past". This is why freshness exists: an
entry is *updated*, never left to accumulate stale ("a stale anchor is worse than
none").

### Structural deposit (lineage)

The STRUCTURAL feed is **generated, not authored**: lineage snapshots live under
`docs/knowledge/lineage/*.json`, committed as the shared snapshot (stable sorted
serialization → clean diffs), full-regenerated, never hand-edited.

**Source-agnostic** — "not only parsing". Any producer normalizes to ONE record
(`nodes:[{key,type}]`, `edges:[{from,to,rel}]`, `generated_at`, `platform`), a
deliberate subset of ade-catalog's `lineage_meta` (the ACT-005 schema-contract
seed) so a future graduation is an ingest, not a rewrite.

| Source | Status | How |
|---|---|---|
| Orchestration (jobs/tasks/notebooks) | ✅ wired | `from_databricks_job_export` over `/databricks-lineage --export` (Jobs API, not parsing) |
| Unity Catalog data-lineage | planned | ingest `system.access.table_lineage` (runtime, reliable) — query, not parse |
| Static code parsing | external | `NotebookIOParser` (ADE) — referenced as a not-yet-present library |
| Fabric warehouse / PBI | external | a `/fabric-lineage` adapter; the `lineage_meta`/ade-catalog graph is deferred |

Deposit: `python -m core.knowledge deposit-lineage --from-databricks-export <f>`.
Query: `python -m core.knowledge lineage <object>` (upstream/downstream). The
ade-catalog cross-platform GRAPH is the scale-out graduation — **deferred** (TICK-024).

## Storage model (same as `core/pm`)

| Layer | What | Tracked? |
|---|---|---|
| **Source of truth** | `docs/knowledge/*.md` (one concept per file, frontmatter + body) + optional `glossary.yaml` (multi-term) | ✅ git — diffable, mergeable, zero-infra |
| **Projection** | `docs/knowledge/index/knowledge.jsonl` — regenerated by `build` | ❌ gitignored, regenerable cache |

The text is the team single source of truth, synced by git. The jsonl is a
per-machine deterministic projection — nobody edits it, you edit the source and
regenerate (exactly the ticket `.md` → `tasks.jsonl` pattern). A future SQLite
projection (file, no server) is the same idea; a live shared DB
(Postgres/Databricks) is the scale-out graduation, gated behind a KnowledgeStore
interface — out of scope for this pilot.

## File layout

```
docs/knowledge/
├── overlay-assembly-pipeline.md     # one concept per file
├── seat-clone-worktree.md
├── glossary.yaml                    # optional: multi-term seed (term -> summary + file_refs)
└── index/knowledge.jsonl            # gitignored projection (build output)
```

One concept per `.md` file: clean git diffs/merges, precise grep hits (the match
*is* the answer), progressive disclosure (read one small file, not a megafile).
The base dir is a parameter — `--base` or `$ADE_KB_BASE`, default `docs/knowledge`
resolved from the repo root.

## Frontmatter schema

```yaml
---
name: overlay-assembly-pipeline     # REQUIRED — kebab slug, unique id
type: concept                       # REQUIRED — concept | decision | glossary | runbook | lineage
summary: src + overlay + patches = what gets deployed   # REQUIRED — one line, shown in list/search
scope: core                         # optional — where it applies (lab | core | <client>/<project> | ...)
file_refs:                          # optional — repo-relative paths this knowledge describes
  - core/engine/overlay.py          #            (the freshness anchor)
last_verified: 2026-06-07           # recommended — ISO date a human last confirmed it true
source_sha: a1b2c3d                 # optional — commit verified against (else derived from file_refs)
ttl_days: 90                        # optional — review-by decay
related:                            # optional — other entry names (like [[name]] memory links)
  - distribution-layout
---
Body markdown — the actual knowledge. Keep it the durable "what / why", not a
copy of the code (the code is the code; link it via file_refs).
```

Soft-validate: a file with missing/unparseable frontmatter still yields a
`needs_cleanup` row — it is surfaced, never silently dropped, never crashes the
build (same contract as the PM index).

## Retrieval discipline (read this before reaching for the index)

| Level | Tool | When |
|---|---|---|
| 1. **Agentic grep** (default) | `Grep` / `Glob` / `Read` on the real files | ~90% of lookups: find a term, a file, an object. **Zero index.** |
| 2. **Deterministic index** | `python -m core.knowledge ...` over the jsonl | Only what grep can't cheaply reconstruct: the curated summary, freshness verdict, lineage, cross-silo "why". |
| 3. **Vector RAG / graph** | — | **Never in this pilot.** Graph (multi-hop lineage w/ audit) is a post-scale target, gated behind ade-catalog. |

"Indexing" here means a **deterministic projection** (extract frontmatter →
jsonl → exact query), not embeddings. No model in the hot path, no infra.

## Freshness contract

The differentiator: a deposited answer must carry "can I trust this?". Computed
cheaply from git (no LLM), CLI/CI-gateable.

| Verdict | Meaning |
|---|---|
| `fresh` | `last_verified` ≥ last commit touching `file_refs`, and within `ttl_days` |
| `stale` | a `file_ref` changed **after** `last_verified` (or `source_sha` ≠ current) — the code moved since the knowledge was confirmed |
| `review-due` | no `file_refs`, but `ttl_days` elapsed since `last_verified` |
| `unverified` | no `last_verified` recorded |
| `unknown` | git unavailable, or `file_refs` not on disk |

**Caveat (notebooks / TMDL / PBIR / SQL / DAX):** AST/symbol-drift is unreliable
for these → freshness uses a coarse **git-age-delta on `file_refs`** (did the file
change after the last verification?), not tree-sitter. A stale verdict is a
*candidate for review*, not proof the knowledge is wrong.

The index/anchor is **generated**, never hand-maintained ("a stale anchor is
worse than none").

## CLI

```
python -m core.knowledge build              # regenerate the jsonl projection
python -m core.knowledge list [--type T]    # all entries: name, type, freshness, summary
python -m core.knowledge show <name>        # one entry: frontmatter + body
python -m core.knowledge search <keyword>   # match name/summary/body
python -m core.knowledge stale              # only entries needing review (freshness != fresh)
python -m core.knowledge glossary <term>    # look up a glossary term
```

## Maturity & promotion

`experimental` → `preview` when: the engine has served ≥3 real lookups that
agentic grep could not cheaply answer, the freshness check has flagged ≥1 real
stale entry correctly, and one operator other than the author has used it. Track
in TICK-024.

## Preview tracking — known unknowns

Specific things NOT yet verified (calibrate trust accordingly):

- [ ] **Glossary scale** — `glossary.yaml` ingest validated only on a small
  seed shape; not tested on a large multi-section glossary.
- [ ] **Freshness on notebooks/TMDL** — git-age-delta logic is implemented, but
  the "stale candidate is actually worth reviewing" precision is unmeasured on
  real `.ipynb`/`.tmdl` churn.
- [ ] **`source_sha` ergonomics** — deriving freshness from `file_refs` works;
  hand-maintaining `source_sha` per entry may rot (the anti-pattern we warn about).
- [ ] **STRUCTURAL layer** — this pilot ships the SEMANTIC layer only. Persisting
  the lineage skills' `tables_read/written` into the index (the structural feed)
  is TICK-024 ACT-002 phase 2, not built.
- [ ] **Cross-machine** — the projection is regenerable and identical by design,
  but the git-sync snapshot boundary (KB as fresh as last pull) is untested on a
  real multi-seat pull cycle.

Full strategy & decisions: `docs/pm/tickets/024-knowledge-base-layer.md`.
