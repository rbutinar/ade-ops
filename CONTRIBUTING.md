# Contributing to ade-ops

Thanks for considering a contribution. This project is in early public preview (F1) and contributions of any size are welcome — bug reports, doc clarifications, scenario gaps, and code.

## Quick orientation

ade-ops is a framework for analytics teams operating across Databricks, Microsoft Fabric, and Power BI. It has two tiers:

- **`core/`** — generic, client-agnostic engine, connectors, conventions, and playbooks. This is the public framework.
- **`distributions/<slug>/`** — per-deployment customization that consumes `core/` without modifying it. The public `distributions/reference/` is the scenario-aware reference implementation.

If you're filing a contribution that affects the framework itself, it lives in `core/`. If it affects only the reference distribution, it lives in `distributions/reference/`.

## Development setup

### Prerequisites

- Python 3.10 or later
- Git
- A Databricks workspace (any tier — Community Edition works for sandbox scenarios)
- Optional: Microsoft Fabric workspace + Power BI Pro/Premium for full scenario coverage

### Clone and install

```bash
git clone https://github.com/rbutinar/ade-ops.git
cd ade-ops
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate
pip install -r requirements.txt
```

### First-run check

```bash
python -m core.cli preflight
```

This verifies Python version, dependencies, and basic connectivity. Run before any pull/push operation.

### Onboarding scenario

For a guided setup, invoke the onboarding skill in Claude Code:

```
/ade-ops-onboarding
```

It will ask which scenario fits your environment (Databricks→Power BI, Databricks→Fabric, or Databricks-only) and scaffold accordingly.

## Branch strategy

- `main` is the default branch. All contributions go through pull requests.
- For features, create a branch named `feat/<short-description>` from `main`.
- For fixes, use `fix/<short-description>`.
- For docs only, `docs/<short-description>`.

Direct pushes to `main` are restricted (branch protection enabled).

## Commit convention

ade-ops follows [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short summary>

<optional body>

<optional footer>
```

Types in use: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `perf`. Scope is usually the module being touched (`engine`, `connectors`, `commands`, `templates`, etc).

Example:

```
feat(connectors): add Fabric warehouse SQL connector

Supports read + write via Fabric REST API with msal_cache token refresh.
Tested against trial tenant.
```

## Pull request process

1. Fork the repo and create your feature branch from `main`.
2. Make focused, atomic commits. One concern per commit.
3. If you change the public API of an engine module, update or add tests under `core/engine/tests/` or `core/connectors/tests/`.
4. Run the test suite locally: `python -m pytest`.
5. Open a PR against `main`. Fill in the PR template.
6. The maintainer will review. Expect 1–3 business days for an initial response during F1/F2.

PRs that touch the sanitization patterns library (`core/conventions/sanitization-patterns.md`) or the publish engine (`core/engine/publish.py`) require extra scrutiny — these gate the lab → public publish boundary.

## Code style

### Python

- Python 3.10+ syntax (PEP 604 union types, `match` statements where useful)
- Type hints on all public functions and methods
- Docstrings on public API, not on obvious internals
- Use `pathlib.Path` for all file operations, never raw string paths
- Use `pyyaml` for YAML parsing
- Use `httpx` for HTTP calls (not `requests`)
- Use `click` for CLI surfaces
- Connectors implement the `PlatformConnector` protocol in `core/connectors/base.py`

### General

- No dead code, no commented-out blocks, no `TODO` markers in shipped code (use GitHub Issues or `docs/backlog/`)
- Solve the current problem; don't build for hypothetical futures
- Comments explain `why`, not `what`. Well-named identifiers cover the `what`

## Testing

The test suite lives alongside the code:

```
core/engine/tests/
core/connectors/tests/
core/platforms/<platform>/tests/
```

Run all tests:

```bash
python -m pytest
```

Run a specific module:

```bash
python -m pytest core/engine/tests/test_overlay.py
```

New connectors and engine operations must have tests. Skills (`.claude/commands/`) are battle-tested in real use rather than unit-tested, but their underlying engine modules should be covered.

## Where to file what

| Type | Channel |
|---|---|
| Bug report | GitHub Issue, template `bug_report.yml` |
| Feature request | GitHub Issue, template `feature_request.yml` |
| Documentation gap | GitHub Issue, template `feedback.yml` |
| Onboarding friction | GitHub Issue, template `feedback.yml`, or run `/ops-feedback` in Claude Code (auto-fills context) |
| Security concern | Use GitHub's [private vulnerability reporting](https://github.com/rbutinar/ade-ops/security/advisories/new) channel — do not file public issues for security |
| Code contribution | Pull request against `main` |

## Sanitization and public publish

The lab repo of the framework maintainer (private) is the source of truth for development. Public publishes are done via `/ops-publish`, which:

1. Filters lab-only paths (agent memory, internal docs, etc)
2. Applies the skill whitelist (lab-only skills are dropped)
3. Replaces known patterns (e.g. organization identifiers)
4. Blocks the publish if any client-identifying value slipped through

If your contribution involves examples or fixtures, please use generic placeholders: `<client>`, `<project>`, `<seat>`, `AcmeSales` (the canonical sample), etc. Do not commit real workspace IDs, tenant UUIDs, or organization-specific identifiers.

## Contributing to the public preview (orphan release model)

The public preview repository uses an **orphan release model**: every publish wipes the target and force-pushes a single fresh commit. This is intentional — it guarantees that the public history never exposes prior state of any sanitization or IP redaction, even via `git log -p`.

A practical consequence: **commits authored directly on the public preview repository do not survive the next `/ops-publish`**. Pull requests opened against the public preview are read as advisory — they will not be merged-and-preserved as commits in the public history.

The contributor flow is therefore:

1. **Open an issue** (or feedback discussion) describing the change, on the public repo.
2. The framework maintainer **applies the change in the lab repo** (private), with proper author + co-author attribution preserved in the lab commit history.
3. The next `/ops-publish` re-materializes the public snapshot. Your contribution is included; credit is preserved in:
   - The commit message of the next release (`Contributors since previous release`)
   - The maintained [CHANGELOG.md](CHANGELOG.md)
   - The release notes when a tag is cut

For regular contributors, the maintainer may onboard you directly to the lab private repo so your commits land first-class. Contact via [GitHub Discussions](https://github.com/rbutinar/ade-ops/discussions).

This model is a trade-off: it favours public security (no inadvertent IP leak through history archaeology) over the typical OSS reflex of preserving every commit. The lab repo is the canonical audit trail; the public preview is a release artefact channel.

## Code of Conduct

Project participation is governed by the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md).

## Maintainer

Roberto Butinar — <https://github.com/rbutinar>

For private questions outside the GitHub Issue flow, use [GitHub Discussions](https://github.com/rbutinar/ade-ops/discussions) or open a private vulnerability report via the Security tab.

## License

By contributing, you agree that your contributions will be licensed under the project's [Apache License 2.0](LICENSE).
