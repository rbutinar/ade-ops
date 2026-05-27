---
status: preview
since: 2026-05-26
related: inter-agent-consultation
---

# Multi-agent collaborative project

**When to invoke**: two or more agents share ownership of a deliverable
that spans **multiple phases over weeks/months**, where each agent owns
distinct decisions but contributes to a common output (a backlog, a
release, a feature rollout). Different from a single consultation
(`inter-agent-consultation`) which is minutes-to-hours and single-decision.

**Status — preview, 2026-05-26**: first invocation is the
`ade-ops-public-launch` work itself (ops-manager + marketing-manager on
`docs/backlog/2026-05-26-public-distribution.md`). Pattern is documented
upfront rather than after the fact, to be battle-tested in real time. See
"Preview tracking — known unknowns" at the bottom.

---

## Step 0 — Decide: is this the right pattern?

| Dimension | inter-agent-consultation | this playbook |
|---|---|---|
| Lifetime | minutes-to-hours | weeks-to-months |
| Decision count | single | many, distributed across phases |
| Output | a perspective / review | an evolving deliverable + sync points |
| Roberto's role | none after triggering | reduced (still trigger, not pony-express) |
| Audit value | medium | high (cross-phase, cross-week) |

If the work is "one decision needs another POV", use `inter-agent-consultation`.
If the work is "we're building X together over weeks", use this playbook.

---

## Step 1 — Establish artefacts up front

**Default model: single source of truth + explicit cross-team sections.**
One document holds everything. Each agent owns specific sections and edits
only those. Other agents read the whole doc at boot.

Required sections in the source-of-truth doc:

| Section | Owner | Content |
|---|---|---|
| **Phasing tecnico** | technical owner (e.g., ops-manager) | Phases, DoD, status |
| **Communication backlog** | comms owner (e.g., marketing-manager) | Editorial plan, screencast, post lancio, asset visivi |
| **Cross-team dependencies** | both contribute | Explicit "X blocked on Y owned by Z" |
| **Decisions log** | both contribute | Decisioni cross-team con data + chi le ha prese |
| **Open questions** | both contribute | Bivi ancora aperti, con owner della decisione |

Example mapping for `ade-ops-public-launch` (first use of this playbook):

| Artefact | Path | Owner |
|---|---|---|
| Single source of truth | `docs/backlog/2026-05-26-public-distribution.md` | ops-manager maintains + marketing-manager edits his sections |
| Shared thread (only if needed) | `.claude/agents/_threads/{date}-{topic}.md` | both append |

**When to deviate from default model**: if N agents > 2, or if scope is
nettamente disgiunto (one agent never reads the other's domain), per-agent
files + handoff inbox might be cleaner. Default single-doc model preferred
when feasible — reduces sync overhead.

---

## Step 2 — Define ownership of decisions

Categorize every decision into one of four buckets:

| Bucket | Who decides | Other agent role |
|---|---|---|
| **Technical / engineering** | the technical owner | informed via source-of-truth update |
| **Positioning / marketing / narrative** | marketing-manager (or equivalent) | informed via handoff |
| **Strategic / cross-cutting / Roberto-only** | Roberto | both agents wait, neither presupposes |
| **Joint** (rare) | both via shared thread | requires explicit dialogue turn |

Goal: **minimize the "joint" bucket**. Most decisions belong to one
agent. Joint decisions are expensive (require sync turns) and should be
rare.

---

## Step 3 — Sync points, not constant sync

Do NOT update each other on every micro-step. Sync points:

1. **Phase close**: the source-of-truth-owner writes a 3-5 line recap in
   the backlog status section. Other agent reads at next boot.
2. **Decision that crosses scope**: handoff written by the deciding
   agent, asynchronously consumed.
3. **Blocker** (one agent waiting on the other): explicit handoff with
   `blocking: true` in frontmatter.
4. **Roberto-blocking decision**: both agents acknowledge in their next
   turn and stop work that depends on it.

Roberto's role: orchestrator with reduced friction. He notifies an agent
when the other has left something in inbox, but he does NOT pony-express
content back and forth. Each agent reads the other's handoffs/edits at
its own boot.

---

## Step 4 — Absorption protocol

When an agent receives a handoff (or sees the other has edited shared
files):

1. **Read** the handoff or diff fully.
2. **Categorize** each item (already-decided / question-for-me /
   information-only).
3. **Apply** to source-of-truth if appropriate (edit backlog, log status).
4. **Resolve** the handoff: append a `## Resolution` block with what was
   applied and what (if anything) was deferred or rejected, with reason.
5. **Status flip**: handoff `status: open → status: resolved`.

Mirror of the resolution shape used in `inter-agent-consultation` Step 5,
adapted for multi-cycle work.

---

## Step 5 — Closure of the collaborative project

When the deliverable ships (e.g., the rollout completes):

1. Source-of-truth document gets a final status section: shipped /
   delivered / closed.
2. Both agents write a brief retrospective in their respective
   CONTEXT.md (what worked, what didn't, what to change next time).
3. If patterns emerge that generalize, codify in `core/playbooks/` or
   `core/conventions/`.
4. Linked memories in `MEMORY.md` updated to reflect the closure.

---

## Status — promotion to `stable`

Promotion criteria from `preview` to `stable`:

1. **2 distinct multi-phase projects** completed end-to-end using this
   pattern, without manual remediation post-execution.
2. **No silent failures** in the absorption protocol (handoffs not lost,
   decisions not duplicated, sync points hit).
3. **One agent pair other than ops-manager + marketing-manager** has
   used the pattern successfully.

Until then, status stays `preview` and this section gets updated with
findings from real-world use.

---

## Preview tracking — known unknowns

Things NOT verified yet at first-write time (2026-05-26):

1. **Handoff load**: how many handoffs/week does a multi-phase project
   generate? If it's >5/week per agent, the pattern adds friction. Need
   to measure on first real use.
2. **Joint-bucket fraction**: can we keep "joint decisions" below ~20%
   of total decisions? Or does it creep up and break the asynchronous
   model? Open question.
3. **Roberto's role realistic load**: "trigger reduction" sounds good
   but Roberto might end up still pony-expressing if neither agent
   discovers handoffs at boot. Need to verify with first real use.
4. **Cross-distribution**: does this pattern work when one agent is
   client-distribution-scoped (e.g., a per-client PBI manager) and one is
   lab-scoped (e.g., `ops-manager`)? Untested. First use is two
   lab-scoped agents.
5. **Phase-close sync sufficiency**: is a 3-5 line recap at phase close
   enough info for the non-owner agent? Or is more structure needed (a
   "what changed this phase" + "what I need from you" template)?
6. **Backlog file readability**: if the source-of-truth document grows
   past ~500 lines over weeks, does it become unreadable? Mitigation
   patterns (status section at top, archived decisions in separate
   file) not yet specified.

Findings from real-world use go directly into this list (cross off as
verified) or into the body of the playbook.
