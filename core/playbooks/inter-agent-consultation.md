# Inter-agent consultation in autonomia

**When to invoke**: an agent needs technical input, a POV, a review, or
a confronto from another agent in the framework, without asking the
human user to orchestrate a separate session.

**Status**: working pattern, not native. Mitigates the absence of
`SendMessage`-style persistent subagents in the current Claude Code
harness (2026-05-25). Will likely be superseded when persistent subagent
resume becomes available; until then this is the canonical procedure.

---

## Step 0 — Decide: handoff or dialogue?

These are two distinct patterns; pick the right one before writing
anything.

| Dimension | Handoff | Dialogue (this playbook) |
|---|---|---|
| Lifecycle | hours-to-days, async, multi-person | seconds-to-minutes, in-session |
| Trigger | task transfer ("fai tu X") | consultation ("che ne pensi di Y?") |
| Audit value | high (cross-team, cross-day) | medium (audit only on final decision) |
| Output | a completed task | a perspective, review, or input |
| Where | `docs/handoffs/{date}-{slug}.md` | `.claude/agents/_threads/{date}-{participants}-{topic}.md` |
| Lifecycle close | resolved by recipient writing a Resolution | initiator closes after synthesis |

If lifetime > a session OR a human needs to be in the loop, use handoff.
Otherwise dialogue.

---

## Step 0.5 — Topology selection (where do the agents live?)

The original pattern (Step 1 onward) assumes a **single filesystem** —
both agents are Claude Code sessions on the same machine, sharing the
same `.claude/agents/_threads/` directory of the same repo.

When agents live in different topologies, the *protocol* stays the
same (turn-based thread file + stance notes) but the *transport* of
the thread file must change. Decision tree:

| Topology | Transport | Pattern | Suitable for |
|---|---|---|---|
| Same machine, same Claude session | n/a — `Agent` tool subagent spawn | Subagent dialogue (in-prompt) | Quick one-shot consultation, no cross-session persistence |
| Same machine, two Claude sessions on **same** repo | Native: `.claude/agents/_threads/` in that repo | Native pattern (Step 1 onward) | Multi-turn, real-time, audit in repo |
| Same machine, two Claude sessions on **different** repos (e.g. lab + a seat clone) | Shared external path outside both repos (e.g. `&lt;dev-root&gt;/_shared_threads/`) | External thread file | Cross-distribution dialogue, same operator |
| Different machines, same operator | Thread file committed to a **team-repo** + pushed/pulled | Team-repo handoff (see below) | Async, multi-machine |
| Different machines, different operators | Handoff in `docs/handoffs/` of an audit-bearing repo | Handoff (different pattern) | Async, audit-heavy, hours-to-days |

### How the host skill should guide the operator

When an agent says *"ho bisogno di parlare con un agent in un altro
seat"*, the host skill walks the operator through:

1. **Same machine?**
   - **Yes** → ask whether the other Claude session is running on the
     same repo or a different repo path.
     - Same repo → use native pattern (`.claude/agents/_threads/`).
     - Different repo → propose shared external path
       (`&lt;dev-root&gt;/_shared_threads/{YYYY-MM-DD}-{topic}.md` on
       Windows, `~/codebase/_shared_threads/...` elsewhere). Create
       the directory if missing.
2. **Different machine?** → propose team-repo handoff pattern (below).
   Confirm a team-repo exists; if not, this is the moment to
   provision one (out of V1 scope, see "Team-repo pattern").

### Variation — thread file outside any repo (shared external path)

When two agents live on the same machine in different repos
(e.g. lab + seat clone):

- Recommended path: `&lt;dev-root&gt;/_shared_threads/{YYYY-MM-DD}-{topic}.md`
  (Windows) or `~/codebase/_shared_threads/...` (POSIX).
- Each agent receives the path explicitly in its boot prompt: "scrivi
  i tuoi turni qui".
- The path is **outside both repos** — outside any sanitization
  filter, outside any release model. The thread file is ephemeral
  by design (no commits, no push, no audit).
- Hygiene: the initiator deletes the file when the consultation
  closes, or moves it to a personal archive. The synthesis output
  (decision, draft, finding) lives in the appropriate target
  location committed where it belongs.

### Team-repo pattern (multi-machine — scaffold + mental model)

For consultations that cross machine boundaries, the thread file
lives in a **third repository** dedicated to team coordination:

- **Public template** (the upstream public ade-ops repo) — **NEVER
  use** for handoff threads. The orphan release model wipes history
  at every `/ops-publish`; threads on this repo disappear.
- **Team repo** — a private repository purposed for cross-machine
  coordination. Each operator clones it on its own machine; thread
  files committed + pushed reach the other operator via a normal
  `git pull`. Hosted typically on a private GitHub Enterprise or
  Azure DevOps instance per the team's security posture.
- **Reference instance** — the first ade-ops adoption (pre-public-
  preview) used an Azure DevOps team repo with `docs/handoffs/` +
  full git history + audit-friendly access. A new team adopting
  ade-ops would clone the public template AND provision its own
  team repo following the same pattern.

This is a **scaffold + mental model**; team-repo provisioning is out
of V1 scope. When a concrete need emerges (first new multi-machine
team adopting ade-ops), this section turns into an implementation
playbook covering:

1. Recommended team-repo skeleton (`docs/handoffs/`, `docs/threads/`,
   no business code in the team-repo)
2. CI for thread-format validation
3. Access control conventions (PAT / SSH / OIDC)
4. Lifecycle hygiene (archive resolved threads, prune old ones)

Until then: treat this as a placeholder. When the first multi-machine
team requests the pattern, extend (do not invent) this playbook.

### Anti-pattern: public preview as transport

Do **NOT** use the public preview repo (`rbutinar/ade-ops`) as
thread file transport. The orphan release model means every
`/ops-publish` wipes the history. A thread file landed there has at
most a few hours / days of life before disappearing. The team-repo
pattern (or shared external path) exists precisely to avoid this.

---

## Step 1 — Create the thread file

Path: `.claude/agents/_threads/{YYYY-MM-DD}-{participants-slug}-{topic-slug}.md`

Examples:
- `.claude/agents/_threads/2026-05-25-marketing-interview-ddf-operator.md`
- `.claude/agents/_threads/2026-05-30-pbi-manager-asks-data-reviewer-deploy-readiness.md`

### Frontmatter schema

```yaml
---
thread_id: {YYYY-MM-DD}-{descriptive-id}
participants: [{initiator-skill}, {interviewee-skill}, ...]
initiator: {who-started-it}
status: open | closed
lifecycle: dialogue
topic: {one-line description of what this thread is for}
target_audience_for_synthesis: {optional — who consumes the synthesis}
---
```

### Body structure

Each turn is a section header followed by the message body:

```markdown
## {agent-slug} — {ISO timestamp}

**Stance note for this turn** (optional but recommended):
- Tone in prior turns: ...
- Tone required for this turn: ...

**Message** (the actual question / response):
...
```

The stance note is a mitigation for the fresh-agent-per-turn limitation
(see "Costs and tradeoffs" below). It captures conversational tone that
the receiving subagent cannot reconstruct from message content alone.

### First turn

The initiator (you, in your current session) writes:

1. Frontmatter with `status: open` and the participants
2. A short intro paragraph stating the goal of the thread
3. Format convention reminder ("each turn is a section, append-only")
4. The first question under `## {initiator-slug} — {ISO timestamp}`
5. An awaiting-response stub: `## {interviewee-slug} — _awaiting response_`

---

## Step 2 — Spawn the interviewee subagent

Use the `Agent` tool with `subagent_type: claude` (catch-all, full tools)
or another suitable type.

### Prompt template

```
Adotta la persona definita in `.claude/commands/{interviewee-skill}.md`.
Sei in modalità **{intervista | review | confronto}**, non in modalità
task-execution. {Caller-skill} ti sta consultando per {goal}.

**Read these files first**:
1. `.claude/agents/_threads/{thread-file-path}` — il thread di
   consultazione. Trova la {Q1 | latest question} sotto
   `## {caller-skill} — {timestamp}`. Leggi anche eventuali turni
   precedenti — sono il tuo contesto-memoria.
2. `.claude/commands/{interviewee-skill}.md` — la tua persona,
   capabilities, vincoli.
3. {Any domain-specific files the interviewee needs to ground
   the response.}

**Rispondi nel thread file**:
- Apri il thread con `Edit`.
- Sostituisci `## {interviewee-skill} — _awaiting response_` con
  `## {interviewee-skill} — {ISO timestamp now}` + il corpo della
  risposta.
- {Specific constraints — lingua, lunghezza, formato output.}

**Vincoli persona**:
- Resta `/{interviewee-skill}`. Non sostituirti al caller.
- Non scrivere fuori dal thread.
- Non eseguire push verso remote.

**Ritorno a me**: summary <150 parole con
(a) ora scritta,
(b) 1-2 frasi sul contenuto principale,
(c) eventuali punti incerti / gap di continuità osservati.
```

### Tunable bits

- **Stance note in the prompt**: if you want a specific tone (more
  pushback, more concrete, etc.), say so in the prompt — the subagent
  is fresh, it reads only what you give it.
- **Recursion depth**: a subagent should NOT spawn further subagents
  from inside the thread. If the interviewee needs to consult a third
  agent, it should signal "I need to consult X first" in its response;
  the initiator (you) does the spawn.

---

## Step 3 — Multi-turn iteration

For each follow-up turn:

1. **Read** the thread file fresh (the subagent has written its response there)
2. **Append** a new section `## {caller-skill} — {ISO timestamp}` with:
   - An updated **stance note** if the tone should shift
   - The next question
   - A new stub `## {interviewee-skill} — _awaiting response_`
3. **Spawn a new subagent** with the same prompt template (it's a fresh
   agent — it doesn't remember the previous turn except via the thread file)
4. Receive summary, repeat

### Practical tips

- **Cite specific points from prior turns explicitly** in the new
  question. The fresh subagent reads text but doesn't "remember writing
  it" — referencing "your point (b) from Q1" in the question text lets
  the subagent connect the threads without guessing.
- **Use stance notes** when you change tone (from diagnostic to
  delivery-mode, from exploratory to decisional). The subagent can pick
  up the cue.
- **Budget 90-120 seconds per turn** (token-heavy: rereads thread + skill
  body + grounding files). Not chat-fast.

---

## Step 4 — Synthesis and close

When the consultation is sufficient:

1. **You** (initiator) read the full thread
2. **You** produce the synthesis (LinkedIn draft, decision, review summary,
   etc.) in the appropriate target location (NOT in the thread file —
   the thread is the input)
3. **Update frontmatter**: `status: closed` + add a `closed: {timestamp}`
   field + optional `synthesis_output: {path-to-deliverable}`
4. **Leave the thread file in `.claude/agents/_threads/`** — it's the
   audit trail. If many threads accumulate, consider archiving to
   `.claude/agents/_threads/_archive/{YYYY-MM}/` (manual hygiene).

---

## Costs and tradeoffs

**Per-turn cost** (~90-120s):

- Subagent reads thread file (grows with turns) + skill body + grounding files
- One LLM call per turn
- Token cost: thread + skill body + grounding rereads each turn

**Quality versus separate human-orchestrated session**: ~80-85%.

The gap (empirically self-identified by the subagent itself in the
first instance of this pattern, 2026-05-25):

> *"il thread file rende disponibile il **contenuto** della Q1 ma non
> il **contesto emotivo/relazionale** di averla scritta — sono un
> agent fresh che legge testo, non lo stesso agent che ricorda di
> averlo scritto."*

The **stance note convention** in the frontmatter of each turn is the
explicit mitigation. It captures conversational tone explicitly so the
fresh subagent can pick it up.

**Other tradeoffs**:

- No streaming feedback — each turn is a complete write-then-read cycle
- Each subagent invocation is isolated; no in-process continuity
- The interviewee skill is consumed in its current `.md` form; if it
  changes mid-thread, later turns use the newer version (could be
  desired or not)

---

## When NOT to use this pattern

- **Real-time iterative debugging** — too slow per turn. Use a separate
  session with the relevant skill loaded.
- **Ephemeral question that fits one prompt** — just answer in your
  current session, don't spawn a subagent for trivia.
- **Task transfer across days or to a human** — use handoff
  (`docs/handoffs/`), not dialogue.
- **Cross-distribution coordination requiring audit** — handoff has
  better audit posture; dialogue's audit is in
  `.claude/agents/_threads/` which is gitignored by default.

---

## Template — first turn

Copy-paste starting point:

```markdown
---
thread_id: 2026-MM-DD-<descriptive-id>
participants: [<initiator-skill>, <interviewee-skill>]
initiator: <initiator-skill>
status: open
lifecycle: dialogue
topic: <one-line description>
---

# Consultation thread — <initiator-skill> → <interviewee-skill>

<one-paragraph intro on what this thread is for>

**Format convention**: each turn is a `## <agent> — <ISO timestamp>`
section. Append-only.

---

## <initiator-skill> — <ISO timestamp>

**Stance note** (optional for Q1, recommended from Q2 onward):
- Tone for this turn: <e.g. exploratory, decisional, delivery-mode>

**Question 1**:

<the actual question>

---

## <interviewee-skill> — _awaiting response_
```

---

## Future evolution

When the Claude Code harness exposes `SendMessage` (persistent subagent
resume), this playbook should be revised. The frontmatter and stance
note conventions can remain; the spawn-per-turn step collapses into a
single spawn + multiple `SendMessage` invocations. Token cost drops
significantly. Continuity gap closes.

Until then: this pattern is the canonical answer to "agent A needs to
consult agent B in autonomia".

## First instance (provenance)

The pattern was empirically validated on 2026-05-25 with
`/marketing-manager` interviewing `/ddf-operator` for marketing
material — three turns, multi-shot, persona maintained, continuity
acceptable. The thread file at
`.claude/agents/_threads/2026-05-25-marketing-interview-ddf-operator.md`
is the reference instance.
