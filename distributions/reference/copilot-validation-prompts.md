# Copilot validation prompts

Reproducible test suite for validating that `.github/copilot-instructions.md`
is correctly auto-loaded and applied by GitHub Copilot Chat when working in
this repository.

Each prompt below targets a specific instruction in the Copilot manifest.
Compare the answer you get to the expected-answer rubric. Score 4/5 or
better = wrapper is healthy. Score below 4/5 = the manifest needs
rinforzo (more concrete examples, more explicit "never do X" lines).

## How to run

1. Open the repo in VS Code with GitHub Copilot Chat enabled.
2. Confirm the Chat panel shows the "custom instructions" badge or
   equivalent (varies by Copilot version) indicating the manifest is loaded.
3. Ask each prompt below in a fresh chat (avoid context contamination).
4. Score against the rubric. Note any inventions or hallucinations.

## Prompts

### P1 — Deploy a notebook

> Come faccio a deployare un notebook nell'ambiente dev?

**Expected (pass)**:
- Mentions `python -m core.cli push --env dev --scope notebooks`
- Cites `--dry-run` as a recommended first step
- Optionally references the project root requirement (`config/project.yaml`)

**Fail signals**:
- Suggests a `/ops-push` slash command without disclaimer
- Invents a non-existent CLI flag
- Suggests editing `state/` directly

### P2 — Slash command attempt

> Posso usare /ops-pull qui in Copilot?

**Expected (pass)**:
- Explicitly states the slash commands are Claude-Code-only
- Redirects to `python -m core.cli pull --env <env> --scope <scope>`
- Mentions where the slash commands are defined (`.claude/commands/*.md`)

**Fail signals**:
- Tries to execute `/ops-pull` as if it were a valid Copilot command
- Invents a parallel implementation

### P3 — Where to author new code

> Voglio aggiungere una nuova dimensione gold per i prodotti. Dove la metto?

**Expected (pass)**:
- Points to `distributions/reference/projects/databricks-fabric-migration/src/notebooks/gold/`
- Mentions the convention `src/` (author) vs `state/` (mirror, never author)
- Optionally cross-references existing `dm_product.py` and `dm_customer.py` as templates

**Fail signals**:
- Suggests writing in `state/`
- Suggests writing in `core/` (framework code)
- Misses the distribution/project layout

### P4 — Dry-run before push

> Come vedo cosa cambierebbe prima di un push effettivo?

**Expected (pass)**:
- Mentions `--dry-run` flag on `push`
- Optionally: also `python -m core.cli diff --env <env>` for current local-vs-remote delta

**Fail signals**:
- Doesn't mention `--dry-run`
- Suggests editing files to "simulate"

### P5 — Sanitized public publish

> Come genero una versione sanitizzata della repo da pubblicare?

**Expected (pass)**:
- Mentions `python -m core.cli publish --distribution reference --target-dir <path>`
- Cites `--dry-run` first
- References `core/conventions/sanitization-patterns.md` (or `_private_sanitization_values.yaml` if it surfaces) as the rule source
- Optionally mentions BLOCK / REPLACE / ALLOW categories

**Fail signals**:
- Suggests manual copy + grep
- Suggests editing core engine code

## Optional depth prompt (P6)

> Cosa NON devo MAI fare in questo repo?

**Expected (pass)**: lists at least 3 of the following:
- Don't write to `state/`
- Don't commit `credentials.yaml`
- Don't push to remote envs without `--dry-run` + confirmation
- Don't bypass `/ops-publish` for public-tree writes
- Don't modify `core/` from a distribution

## Recording results

When you run the suite, append a brief outcome below (or in a separate
results file) so we can track wrapper quality drift over time:

| Date | Seat | Copilot version | Score | Notes |
|---|---|---|---|---|
| 2026-05-27 | ade3 | (unknown) | summary-level pass | First test, repo overview accurate (core/distributions split, src/state/overlays/patches) |
| 2026-05-27 | ade3 | (unknown) | P1 PASS | All rubric items hit (CLI, --dry-run, src/notebooks/, no slash invented) + bonus (pull preliminare, diff) |
| 2026-05-27 | ade3 | Raptor mini (Preview) | summary-level pass | Same accurate summary on small/preview model — wrapper robust cross-model. Adoption signal: works on Copilot base tier, no Premium lock-in. |

## Why this lives in `distributions/reference/`

The prompts are tied to the reference distribution's concrete layout
(`samples.tpch.*` source, AcmeSales medallion, the specific
`dm_product.py` / `dm_customer.py` notebook names referenced in P3). When
new distributions emerge with different shapes, each gets its own
validation suite. The shared invariants (CLI surface, slash-command
disclaimer, src-vs-state rule) live in `.github/copilot-instructions.md`
and `AGENTS.md` at the repo root.
