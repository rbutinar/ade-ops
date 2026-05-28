---
date: 2026-05-28
type: bug
severity: normal
persona: ops-local-manager
status: open
project: null
branch: feedback/ops-local-manager-gitignore
commit: 5362b34
cwd: C:\codebase\ade-ops-1
---

# .gitignore missing entries for /ops-local-manager local state

## Detail

The `/ops-local-manager` skill spec (`.claude/commands/ops-local-manager.md`)
declares these per-clone local-state files as gitignored:

- `.claude/agents/ops-local-manager/CONTEXT.md`
- `.claude/agents/ops-local-manager/IDENTITY.md`
- `.claude/agents/ops-local-manager/users/{handle}.md`
- `.claude/agents/ops-local-manager/sessions/`

Quote from the spec:

> "Memory (`CONTEXT.md`, `IDENTITY.md`, `sessions/`) and working state
> (`drafts/`, `sources/`, `local/`, `handoffs/`) can coexist here while
> these conditions hold"

and explicitly for per-user files:

> "Gitignored, never committed."

However the repo's `.gitignore` does **not** cover them. The pattern is
established for sibling agents — `marketing-manager` (line 67-70) is
ignored wholesale, and `_threads/` (line 73) is ignored — but the
`ops-local-manager` entry is missing.

### Observed behaviour

At the first boot of `/ops-local-manager` on a fresh clone, the skill
bootstraps memory from the templates:

```
cp CONTEXT.template.md → CONTEXT.md
cp IDENTITY.template.md → IDENTITY.md
mkdir -p sessions/
```

Then writes `users/{handle}.md` over time. All three of these immediately
appear as untracked in `git status`:

```
?? .claude/agents/ops-local-manager/CONTEXT.md
?? .claude/agents/ops-local-manager/IDENTITY.md
?? .claude/agents/ops-local-manager/users/r.butinar.md
```

### Impact

- **Risk of accidental commit**: any operator using `git add -A` /
  `git add .` will sweep in per-clone state — including the friction
  log in `users/{handle}.md` which may contain operator-private notes.
- **Spec/reality drift**: the skill body promises gitignored behaviour
  that the repo doesn't actually deliver, eroding trust in the spec.
- **Hits every adopter on day 1**: there is no way to invoke
  `/ops-local-manager` without producing these untracked files (the
  boot step is mandatory and starts with the bootstrap).

### Why "bug" not "missing-feature"

The spec already declares the contract. The repo doesn't fulfill it.
That's a bug, not a missing feature.

## Proposed fix

Add to `.gitignore` (suggest grouping near the existing
`marketing-manager` / `_threads/` block around line 67-73):

```gitignore
# /ops-local-manager — per-clone local state (templates are committed,
# the bootstrapped files and friction logs are not).
# Skill spec declares these gitignored; see .claude/commands/ops-local-manager.md.
.claude/agents/ops-local-manager/CONTEXT.md
.claude/agents/ops-local-manager/IDENTITY.md
.claude/agents/ops-local-manager/users/
.claude/agents/ops-local-manager/sessions/
```

Note the selective scope: **templates** (`CONTEXT.template.md`,
`IDENTITY.template.md`) and the agent definition files MUST stay
tracked — they ship with the framework. Only the bootstrapped/local
copies are ignored.

This differs from the `marketing-manager` pattern (which ignores the
whole dir wholesale) because `ops-local-manager` is a framework agent
that needs to ship its templates and definition; only the local state
within it is per-clone.

## Auto-captured context

- **Date**: 2026-05-28
- **Persona**: ops-local-manager
- **Project**: null (cwd is repo root, not inside a project tree)
- **Branch**: feedback/ops-local-manager-gitignore
- **Commit**: 5362b34
- **Cwd**: C:\codebase\ade-ops-1

### Recent ops.log

```
(no ops.log found — cwd is not inside a project tree)
```
