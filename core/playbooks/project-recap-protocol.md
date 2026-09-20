---
status: preview
since: 2026-05-26
related: inter-agent-consultation, multi-agent-collaborative-project
---

# Project recap protocol

**When to invoke**: when the user asks for a "recap", "stato progetto",
"punto situazione", "cosa abbiamo da fare", "dove siamo arrivati". The
agent needs to synthesize multi-source state into a scannable,
action-prioritized view — not a chronological log.

**Status — preview, 2026-05-26**: codified from a real ops-manager recap
exercise (`docs/backlog/2026-05-26-public-distribution.md` work, recap
turn at end of session). Pattern extracted upfront to enable other skills
(operative or meta) to reproduce same-quality recaps. To be battle-tested
on the next "recap" request to a non-ops-manager skill.

---

## Step 1 — Identify sources (in order of authority)

| Source | What it carries | Typical path |
|---|---|---|
| **Persistent memory header** | "Next session entry point" — wait state, promotion radar, pending lab block | `.claude/agents/{slug}/CONTEXT.md` (meta-agent only) |
| **Operations log** | Narrative of what was done/closed recently | `docs/ops.log` or `distributions/{client}/projects/{project}/ops.log` |
| **Backlog folder** | Initiatives in flight with phasing/status | `docs/backlog/*.md` |
| **Persistent memory references** | Long-term references, decisions, learned behaviors | `~/.claude/projects/{slug}/memory/MEMORY.md` (auto-loaded as system context) |
| **Working memory** (current conversation) | Recent edits, in-flight decisions | conversation context (volatile, NOT durable) |

For each source: read it at startup or on-demand. Working memory is
**not** authoritative — it's the volatile delta since last commit.

---

## Step 2 — Categorize into action-priority buckets

Five buckets, in order of urgency for the user:

1. **Pending decisor** — user-blocking decisions. The agent has done its
   part; the user must respond. Comes first because it's the only
   actionable item from the user side.
2. **Active** — in-flight work with phasing, target dates, owner is the
   agent. The agent's near-term schedule.
3. **Parallel track** — concurrent work driven by other agents/people
   where this agent is the recipient or observer, not the driver.
4. **Trigger-based** — wait states, promotion candidates, condition-gated
   items. Nothing to do until a signal arrives.
5. **Deferred / closed recente** — reference only. Closed items
   referenced for traceability, no action needed.

**Critical**: order is by action-priority, NOT chronological, NOT
alphabetical. The user reads the recap to know what to do next.

---

## Step 3 — Map each item on orthogonal dimensions

Per item, populate:

- **Phase / status** (planning / in-progress / shipped-preview / stable / deferred / closed)
- **Effort** (X hours / X days / TBD)
- **Target date** if applicable
- **Trigger condition** if wait state ("when X happens, then Y")
- **Owner** (the agent itself / another agent / Roberto)

If a wait-state item is missing its trigger condition, the recap is
**incomplete** — surface this as a gap, do not paper over it.

---

## Step 4 — Format: scannable tables per bucket

Each bucket = one table. Columns chosen to fit the bucket (e.g., Active
has Phase/Effort/Target; Trigger-based has Status/Trigger Condition).

Avoid prose paragraphs for state. Tables compress and let the user
diff-scan. Reserve prose for context that wraps a table (e.g., "this is
new this week").

---

## Step 5 — Surface fragility

Always include a final "what's robust vs fragile in this recap"
self-assessment, e.g.:

- ✅ Robust: backlog file phasing + decisions log (committed)
- ⚠️ Fragile: working memory of current discussion not yet persisted

This lets the user decide whether to commit/save before closing session.

---

## Adaptation per skill type

Different skills have different persistence infrastructure. Map the
sources accordingly:

| Source category | Meta-agent (e.g., `/ops-manager`) | Operative skill (e.g., distribution-level PBI manager, onboarding agent) |
|---|---|---|
| Persistent memory header | `.claude/agents/{slug}/CONTEXT.md` | Not available → use distribution/project `CLAUDE.md` as static-context proxy |
| Operations log | `docs/ops.log` (framework) | `distributions/{client}/projects/{project}/ops.log` (team-level, less granular) |
| Backlog folder | `docs/backlog/*` | Not standard → use `docs/handoffs/` (work-in-flight inbox) as backlog proxy |
| Persistent memory references | `MEMORY.md` (auto) | Same `MEMORY.md` — shared per project, not per skill |
| Promotion radar | CONTEXT.md section | Not available → infer from skill frontmatter `status: preview/stable` |
| Decisions log | CONTEXT.md or backlog file | Inferable from `git log` recent + handoff Resolution blocks |
| Recent change signal | sessions/ + git log | `git log --since=<recent>` last 5-10 commits as fallback |

**Critical adaptation for operative skills**: when CONTEXT.md is absent,
use `git log` recent commits + handoffs folder + `CLAUDE.md` as
substitute. Acknowledge degradation explicitly in Step 5 fragility
section (e.g., "no decisions log available — promotion radar inferred
from skill frontmatter, may miss recent verbal decisions").

---

## Status — promotion to `stable`

Promotion criteria from `preview` to `stable`:

1. **3+ distinct recap requests served** with this protocol, no
   incompleteness signaled by the user as critical.
2. **1+ operative skill** (NOT ops-manager) has applied the protocol
   successfully — battle-test on a distribution-level skill or equivalent.
3. **Gap-list** of "what's missing when applied to operative skills"
   categorized: which gaps are persistence-infra (need investment) vs
   which gaps are skill-specific (no action).

Until then, status stays `preview`.

---

## Preview tracking — known unknowns

Things NOT verified yet at first-write time:

1. **5 buckets sufficient?** Could a 6th bucket be needed
   ("deferred-with-deadline", "blocked-on-external")? Unknown until
   battle-tested.
2. **Adaptation for operative skills**: gap-list is theoretical (Step 4
   adaptation table). Real test = ask a distribution-level PBI manager
   skill for a project recap and observe what's missing.
3. **Recap length cap**: when does a recap become unreadable? Should
   there be a soft cap (max N items per bucket) or smarter prioritization
   (top-3 active, all pending, all blocking, rest collapsed)?
4. **Scope clarification step**: should there be a Step 0 "clarify
   scope" (e.g., "recap of WHICH project?") when ambiguous? Today's run
   was unambiguous because conversation context was rich, but a
   cold-start recap to a meta-agent might need explicit scope-pick.
5. **Fragility surfacing**: is Step 5 too defensive? Or essential to
   avoid the user assuming everything is committed when it isn't? First
   real test will tell.
6. **Cross-skill recap**: what if the user asks "recap del framework
   tutto" spanning ops-manager + marketing-manager + a distribution-level
   PBI manager? Today's protocol assumes single-skill scope. Multi-skill
   recap protocol = separate playbook? Or extension?

Findings from real-world use update this list directly or land in the
playbook body.

---

## How agents invoke this

When an agent (any skill) is asked for a recap, the agent should:

1. Read this playbook (`core/playbooks/project-recap-protocol.md`) if
   not already loaded.
2. Apply Step 1-5 in order. Skip steps that don't apply to its
   persistence infra (per Step 6 adaptation), and **explicitly note the
   skip in Step 5 fragility**.
3. If new gaps emerge that aren't in "Known unknowns", append them to
   the playbook body (under "Preview tracking") and surface to the user
   as a meta-finding worth tracking.

This protocol is a working pattern, not a rigid template — agents adapt
it to their context. The goal is action-prioritized, scannable,
fragility-aware recaps. The form serves the goal, not vice versa.
