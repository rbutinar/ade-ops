---
name: ops-session-close
status: preview
since: 2026-05-28
related: ops-dev, ops-prod, ops-review, ops-status
---

# /ops-session-close — Close a seat session with a structured recap

> **Status**: preview. Part of the identity / context / ops triad
> (`core/conventions/seat-triad.md`). Surfaced by the boot UX of operator
> skills (`/ops-dev`, `/ops-prod`, `/ops-review`) when the previous
> session is still in `in_progress`.

## What it does

Writes a structured session log under
`distributions/<dist>/.seat-sessions/YYYY-MM-DD_<topic>.md` using
`core/templates/seat-session.md`. The log is gitignored (per-seat
durable memory) and is read at next seat open to recreate continuity
without forcing the operator to recall context manually.

The session log is the seat-level analogue of `CONTEXT.md` files that
agents (like `/ops-manager` or `/ddf-operator`) keep under
`.claude/agents/<role>/`. While the agent CONTEXT is *per-Claude-role*,
this session log is *per-seat* — it persists work done on a particular
clone-and-distribution pair regardless of which agent ran the commands.

## When to use

Invoke `/ops-session-close` when:

- You are wrapping up a focused work session (1+ hour of activity, or
  a meaningful unit of work that future-you would benefit from remembering).
- You have shipped commits, opened findings, or left the working tree
  in a non-trivial state.
- You are about to step away and don't know when you'll be back —
  the recap captures continuity context that decays from memory.

Skip when:

- The session was purely consultative (no state changes).
- You are still actively in-flight — write a "checkpoint" not a "close".

## Usage

```bash
/ops-session-close
/ops-session-close --topic "databricks-pull-debug"
/ops-session-close --resume   # re-open the last session for further edits
```

Options (executed by the host skill, not the engine):

- `--topic <slug>` — kebab-case topic used in the filename. If omitted,
  the skill suggests one based on the most active scope.
- `--resume` — re-open the most recent session for amendment instead
  of creating a new file.

## Pipeline summary

When you invoke this skill, the agent does the following:

1. **Detect seat** — read `distributions/<dist>/.seat.yaml` to bind
   seat name + distribution + role. Fall back to clone-path basename
   if no manifest exists.

2. **Collect raw inputs**:
   - `git log --since='<session_start>'` in the seat repo
   - `git status` for working-tree dirty state
   - Tail of `ops.log` (project-level and lab-level)
   - List of `/ops-feedback` files written during the session
   - Any open tasks tracked by the agent

3. **Synthesise the seven sections** of `core/templates/seat-session.md`:
   Goal, Outcome, Commits shipped, Findings opened, State at session
   close, Next session entry point, plus the YAML frontmatter for
   tooling.

4. **Write** to
   `distributions/<dist>/.seat-sessions/YYYY-MM-DD_<topic>.md`. If a
   file with the same name exists, append `_v2`, `_v3`, etc.

5. **Update ops.log** with a `SESSION-CLOSE` entry pointing at the file.

6. **Surface a one-liner** to the operator: "Wrote session log at
   `<path>`. Next session boot will pick this up."

## Preview tracking — known unknowns

Specific items not yet verified at first-ship time (2026-05-28):

1. **Auto-detect session_start**: V1 takes the earliest entry from the
   project-level `ops.log` whose timestamp is on the current calendar
   day. Needs refinement for multi-session days and overnight sessions.

2. **`--resume` semantics**: V1 just opens the latest file in the
   seat-sessions dir. Does not detect if the previous session was
   "closed" intentionally vs abandoned.

3. **Boot UX hook**: operator skills (`/ops-dev`, `/ops-prod`,
   `/ops-review`) need explicit startup steps to read the latest
   session-recap. V1 ships the convention only; per-skill body updates
   land as separate task.

4. **Integration with agent CONTEXT.md**: when the same operator runs
   under an agent (e.g. `/ops-manager`), there are now *two* recap
   surfaces (agent CONTEXT.md + per-seat session log). Convention so
   far: CONTEXT.md is per-agent-role across multiple sessions on the
   same seat; session log is per-session across multiple agent-roles
   on the same seat. Overlap is acceptable for now; rationalise at
   battle-test #3.

## Status — promotion to `stable`

Promotion from `preview` to `stable`:

1. 3+ real-world sessions closed by different operators (incl. at
   least one non-author operator) with the resulting recap being
   readable as continuity input by the next session.
2. Boot UX hook landed in at least one operator skill (`/ops-dev`
   most likely first).
3. No silent failures: dirty state, mid-session crashes, and abandoned
   sessions all produce honest recaps (not "ok").

ARGUMENTS: $ARGUMENTS
