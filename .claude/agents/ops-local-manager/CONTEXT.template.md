# Ops Local Manager — CONTEXT

> This file is the **global notes** of the local steward agent for this
> distribution. Bootstrap at first run by copying `CONTEXT.template.md`
> → `CONTEXT.md`. Both files live in `.claude/agents/ops-local-manager/`.
> `CONTEXT.md` is gitignored — content evolves per-clone.

## What goes here

- **Skill evolution decisions** made during the lifetime of this clone
  (e.g. "we decided to use modality 3 credentials for HOST values, not
  modality 2, after 2026-05-28 cross-seat conflict")
- **Distribution-specific milestones** that mark "framework progressed
  here, downstream operative action is needed"
- **Hand-off conventions** that the team adopted but are not yet in
  framework conventions (informal until codified)
- **Open questions** to revisit next session

## What does NOT go here

- Per-user state (graduation date, last persona) → `users/{handle}.md`
- Operations audit (push / pull / diff outcomes) → `ops.log` of each
  project
- Session-by-session recaps → `distributions/<dist>/.seat-sessions/`
  via `/ops-session-close`
- Lessons-learned waiting for `/ops-feedback` filing → friction log in
  `users/{handle}.md`

## Format

Free-form Markdown. The skill at boot does NOT parse this file — it
just reads it for the operator's awareness. Headings recommended:

```markdown
## Skill evolution

- 2026-05-28: switched to modality 3 for DATABRICKS_HOST after cross-
  seat conflict ([[reference-credentials-convention]]).

## Open questions

- Should we adopt /ops-operator autopilot for nightly migrations?
  Decision: defer until 2 successful manual runs.

## Distribution milestones

(maintained by the framework maintainer side; this clone notes which
ones have been actioned)
```

## Maintenance

Updated by the operator when something memory-worthy happens. The
skill `/ops-local-manager` does NOT auto-write here at session close —
that responsibility is on the operator (the skill may propose specific
entries when patterns warrant; the operator confirms).
