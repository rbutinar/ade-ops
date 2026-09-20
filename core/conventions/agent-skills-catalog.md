# Agent-Skills catalog — single source, projected to every harness

**Status:** adopted (lab + a client distribution) · validated for Copilot + Codex · other harnesses pending
**Since:** 2026-07-04 (TICK-010)

## The finding (why this exists)

`SKILL.md` is the open Agent-Skills standard — one authored file works across ~20+
agents (Claude Code, Copilot, Codex, Gemini CLI, Cursor, Antigravity, Windsurf, …).
The **content** is unified. What is **not** unified is the **location** each harness
scans, and that bites:

- **Claude Code** reads `.claude/skills/` (its native namespace). *Does not* read `.agents/skills/`.
- **GitHub Copilot** reads `.claude/skills/` (+ `.github/skills/`, `.agents/skills/`).
- **OpenAI Codex** reads the vendor-neutral **`.agents/skills/`** — and does **not** fall
  back to `.claude/skills/` (proven 2026-07-04: deleting `.agents/skills/` → Codex saw 0).

So no single physical path is read by all harnesses. A skill also needs a well-formed
**`description`** in its frontmatter: strict consumers (Codex, Copilot) index on it to
*discover* and *auto-trigger* the skill — Claude Code is lenient (derives from folder +
H1), which is why a missing `description` looks fine in Claude Code but hides the skill
elsewhere. On 2026-07-04, 55 of 57 lab skills lacked `description` → Codex saw only the
2 that had one.

## The standard

1. **Single source of truth:** author skills once in `.claude/skills/<name>/SKILL.md`
   (Claude native + the authoring standard). Every skill carries frontmatter `name`
   (folder slug), a real `description` (*what it does + when to use it*), and `status`
   (maturity convention).
2. **Projection (dual catalog):** the source is mirrored into the vendor-neutral
   `.agents/skills/` by [`tools/sync_agent_skills.py`](../../tools/sync_agent_skills.py)
   — an exact mirror (stale entries removed), idempotent. You edit `.claude/skills/`
   only; the projection is a **generated artifact** and is **gitignored** (`.agents/`).
3. **Anti-drift wiring:** the projection must be regenerated after any skill change, or
   it goes stale (the original bug). Two hooks keep it fresh:
   - **pre-commit** — `.githooks/pre-commit` runs the projector. Activate per clone:
     `git config core.hooksPath .githooks`.
   - **seat / onboarding** — the launcher runs `python -m tools.sync_agent_skills` at
     session start so a fresh clone's projection exists before any harness opens.
   - **CI / publish** — `python -m tools.sync_agent_skills --check` fails if drifted.

## Cross-harness location matrix

| Harness | Reads | Covered by |
|---|---|---|
| Claude Code | `.claude/skills/` (+ `~/.claude/skills/`) | source |
| GitHub Copilot | `.claude/skills/` (+ `.github/skills/`, `.agents/skills/`) | source |
| OpenAI Codex | `.agents/skills/` | projection |
| Cursor | `~/.cursor/skills/` (global) | *pending* — seat launcher |
| Google Antigravity | `~/.gemini/config/skills/` (global) | *pending* — seat launcher |
| Gemini CLI / Windsurf / Cline | mixed, via the standard | *pending* |

Project-level neutral catalogs live in the repo (`TARGETS` in the projector). Global
per-user catalogs (Cursor, Antigravity) are populated by the seat/onboarding launcher,
not committed — add them when validated.

## New-skill checklist

1. Author `.claude/skills/<name>/SKILL.md` with `name` + a real `description` + `status`.
2. `python -m tools.sync_agent_skills`
3. `python -m tools.sync_agent_skills --check` → in sync.
4. (Cross-harness) reload the target harness and confirm the skill appears.

## Scope & rollout

Adopted on the lab and propagated to a client distribution (2026-07). Other distributions/farm repos
adopt on-demand (they carry `tools/sync_agent_skills.py` + the hook + the `.agents/`
gitignore, then run the projector). Extend `TARGETS` / the launcher as more harnesses
are validated.
