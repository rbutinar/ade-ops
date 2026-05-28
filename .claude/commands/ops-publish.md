---
name: ops-publish
status: experimental
since: 2026-05-26
related: ops-init, ops-sync, ade-ops-onboarding
---

# /ops-publish — Publish a distribution to a public target

> **Status**: experimental. F1.2 MVP shipped 2026-05-26 (engine + CLI).
> Orphan release model added 2026-05-28 (F1.x absorb ade-ops-2 wave 1).
> See `core/conventions/sanitization-patterns.md` for the rule library
> consumed by this skill, and `docs/backlog/2026-05-26-public-distribution.md`
> for the broader F1/F2/F3 rollout context.

## Release model — orphan-by-default

The public preview is a release artefact, not a development workshop. The
default behaviour is:

1. **Wipe** the target directory before writing the new snapshot (no
   resumption of any prior `.git/` history).
2. **Materialise** the sanitized publish into the empty target.
3. **(With `--push`) Force-push** a single fresh commit to the remote
   branch — the prior remote history is replaced atomically.

This guarantees that the public repository never reveals through
`git log -p` what was sanitized, what was redacted, or which IP fixes
landed when. Full provenance — author, co-author, date, conversation
context — lives in the lab private repo (`rbutinar/ade-ops-lab`).

Opt-out via `--preserve-history` exists for the rare incremental publish
(e.g. CI re-run after a transient failure). It is intentionally NOT the
default and is **not recommended** for public targets — it leaks the
shape of changes between snapshots into the public history.

Attribution for external contributors who land work in the lab (via PR
to the private repo) is preserved via the commit message body and a
maintained `CHANGELOG.md`. See `CONTRIBUTING.md` "Contributing to the
public preview" for the contributor flow.

## What it does

Materialises a publish-ready snapshot of one distribution into a target directory, applying:

1. **Path filter** — drops lab-only paths (`ops.log`, `feedback/`, `backlog/`, agent memory, `marketing-manager/**`, other distributions, `state/`, credentials, `.mcp.json`, `__pycache__`, `.git/`, etc.).
2. **Skill whitelist** — reads the distribution's `project.yaml` `skills.include` list and prunes `.claude/commands/` accordingly. Falls back to a hardcoded default-deny prefix list (`<client>-*`, `ddf-*`, `marketing-*`, `ops-manager`, `ops-port-back`, `weekly-team-*`) when no whitelist is configured.
3. **REPLACE rules** — auto-substitutes patterns like `<organization>` → `<organization>` in markdown/Python/YAML prose. Each substitution is logged in the publish report.
4. **BLOCK rules** — refuses to write any file whose post-REPLACE content matches a BLOCK pattern (real Databricks hosts, UPN values, client slugs, personal paths, person names, etc.). Returns the violation list with file + line + pattern name.
5. **ALLOW assertions** — verifies positive patterns are present in the materialised target (e.g. `Roberto Butinar` in `LICENSE`, `Apache License Version 2.0` in `LICENSE`).
6. **Confirm-before-write** — interactive prompt unless `--yes` is passed.
7. **Idempotent** — re-running on a populated target overwrites changed files; nothing is deleted.

The patterns file `core/conventions/sanitization-patterns.md` is self-exempt from BLOCK + REPLACE scans (it cites its own pattern literals as examples in the tables).

## When to use

- **F1.5 first publish**: initial commit of `rbutinar/ade-ops` public repo (private/public visibility decided at `gh repo create`).
- **Subsequent publishes**: when `core/` or `distributions/<slug>/` evolve in the lab and the public should receive the update.
- **Pre-flight before a release**: always run with `--dry-run` first to surface violations + replacements without writing.

## Usage

```bash
# Always dry-run first to see violations + replacements
python -m core.cli publish \
  --distribution reference \
  --target-dir /tmp/ade-ops-public-staging \
  --dry-run

# Local-only publish (no push) — wipes target, materialises snapshot
python -m core.cli publish \
  --distribution reference \
  --target-dir /tmp/ade-ops-public-staging

# Full orphan release to GitHub (wipe + write + init + force-push)
python -m core.cli publish \
  --distribution reference \
  --target-dir /tmp/ade-ops-public-staging \
  --push https://github.com/rbutinar/ade-ops.git \
  --publish-as-name "Roberto Butinar" \
  --publish-as-email "12345+rbutinar@users.noreply.github.com" \
  --yes

# Incremental publish (opt-out from orphan model — not recommended for public)
python -m core.cli publish \
  --distribution reference \
  --target-dir /tmp/ade-ops-public-staging \
  --preserve-history
```

Options:

- `--distribution`, `-d` — distribution slug (e.g. `reference`)
- `--target-dir`, `-t` — destination directory (created if missing)
- `--dry-run` — compute without writing; safe to run anytime
- `--lab-root`, `-l` — lab repo root (default: nearest ancestor with `core/` + `distributions/`)
- `--yes`, `-y` — skip the confirm-before-write prompt
- `--preserve-history` — opt out from the orphan model (no wipe, incremental over existing `.git`). Mutually exclusive with `--push`.
- `--push <remote-url>` — after write, `git init` + single commit + force-push to this remote
- `--branch <name>` — branch to push to (default `main`)
- `--publish-as-name <name>` / `--publish-as-email <email>` — override commit identity (for public releases use a GitHub no-reply email)

## Output

On a clean publish:

```
Files to publish : 109
Replacements     : 0
BLOCK violations : 0

Replacements (auto-substituted):
  ...

Published 109 files to /tmp/ade-ops-public-staging
```

On a blocked publish (exit 1):

```
BLOCKED: cannot publish until the following are fixed in source
  [client-slug-<client>] 68 match(es)
  [client-slug-<project>] 17 match(es)
  ...

Sample (first 10):
  .claude/commands/fabric-extract-v2.md:7 pattern=client-slug-<client> match='<client>'
  ...
```

## Noqa exemption

When a BLOCK pattern hits a legitimate use that's costly to refactor, add an inline marker on the same line:

- Python: `# noqa: ade-ops-sanitize=<pattern-name> reason="..."`
- Markdown: `<!-- noqa: ade-ops-sanitize=<pattern-name> reason="..." -->`

The publish engine honours the marker per-line, per-pattern.

## Pipeline summary

1. Walk lab from ancestor with `core/` + `distributions/`
2. Apply path filter (lab-only globs + slug-based distro filter)
3. Apply skill filter (`skills.include` whitelist or default-deny prefixes)
4. For each text file:
   - Apply REPLACE rules in scope → substituted text
   - Scan BLOCK rules in scope on the substituted text → violations
5. If any BLOCK violation → print summary, exit 1, no write
6. Confirm-before-write prompt (skip with `--yes`)
7. Write files (binary copy for non-text extensions)
8. Verify ALLOW assertions on the materialised target
9. Exit 0 (success) or 1 (ALLOW miss after write — warn user)

## Preview tracking — known unknowns

Specific items not yet verified at first-write time (2026-05-26):

1. **First real publish to GitHub**: smoke tested locally against `/tmp/ade-ops-public-staging` only. F1.5 will be the first end-to-end live invocation against `rbutinar/ade-ops` public repo.
2. **ALLOW assertions need LICENSE/README**: F1.4 ships these — until then, the publish writes successfully but ALLOW step emits warnings (expected).
3. **Multi-project distributions**: V1 picks the first project's `skills.include`. Needs refinement when a 2nd reference distribution emerges.
4. **Self-exempt of `sanitization-patterns.md`**: works as designed in smoke; not battle-tested with patterns file rotation across versions.
5. **Replacement of `${GITHUB_NOREPLY_EMAIL}` literal**: the REPLACE rule for Roberto's email maps to a placeholder string; F1.5 needs to wire the actual no-reply email before live publish (planned: passed via env var or `--maintainer-email` flag, V2).
6. **Binary file detection**: relies on extension allow-list (`_TEXT_EXTENSIONS`). UTF-8 decode fallback handles edge cases. Unverified for `.tmdl` files with unusual encoding.

## Status — promotion to `stable`

Promotion criteria from `experimental` to `preview`:

1. F1.5 first real publish to GitHub completes with zero BLOCK violations.
2. F2 at least 1 subsequent publish from updated lab state.
3. `/ade-ops-onboarding` smoke-test on a clean clone of the published target passes scenario D end-to-end.

Promotion from `preview` to `stable`:

1. 3+ publishes across at least 2 weeks without manual remediation.
2. 1+ contributor (non-author) has successfully run a publish.
3. All preview-tracking items above resolved.

ARGUMENTS: $ARGUMENTS
