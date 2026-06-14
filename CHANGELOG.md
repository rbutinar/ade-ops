# Changelog

All notable changes to **ade-ops** public preview are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) loosely. The project uses an **orphan release model** (see `CONTRIBUTING.md`): every `/ops-publish` rewrites the public history. This file is the durable record of what landed in each release, since the git log alone reflects only the latest snapshot.

## [Unreleased]

Pending changes accumulated in the lab repo, to be materialised on the next `/ops-publish`.

### Repository visibility

- **2026-05-28: `rbutinar/ade-ops` is now PUBLIC.** The repository transitioned from private bootstrap to public preview after green-light on the double-test (clone-from-scratch run on a fresh seat) and a clean security scan. Updates continue to land via `/ops-publish` orphan releases (see `CONTRIBUTING.md`); direct pushes to this repo are not accepted.
- Private vulnerability reporting (PVR) enabled — report security issues at https://github.com/rbutinar/ade-ops/security/advisories/new.
- GitHub Discussions enabled with a custom **`Feedback`** category for open-ended feedback, friction reports, and half-formed thoughts (sibling of the structured Feedback issue form).

### Added — community surface

- **`.github/DISCUSSION_TEMPLATE/feedback.yml`** — discussion template that prefills the `Feedback` category with light prompts ("what's the friction?", "where in the flow?", "what were you trying to do?"). Cross-links to the structured Feedback issue form for actionable items.
- **README "Where to file what"** table — disambiguates the six channels (bug / feature / structured feedback / open-ended discussion / private preview signup / security disclosure) so contributors don't have to guess.

### Added — security policy

- **`SECURITY.md` `## Threat model` section** — explicit `Trusted inputs` / `Untrusted inputs` / `Out of scope` blocks that calibrate human and LLM security reviewers on what is attack surface for a local CLI + agent that runs with the operator's credentials against the operator's own infra. Closes the gap where `/security-review` defaulted to a SaaS/multi-tenant threat model and surfaced two HIGH false-positives on `source_table` (CLI arg) and `overlay:` field (operator-authored config). Driver: dogfooding finding `feedback/threat-model-section` from seat `ade-ops-1` (commit `5362b34`).

### Fixed — gitignore

- **`.gitignore` covers `/ops-local-manager` per-clone state** — selective block added: `CONTEXT.md`, `IDENTITY.md`, `users/`, `sessions/` ignored; templates and agent definition stay tracked. The skill spec already declared these gitignored, but the repo's `.gitignore` did not deliver. Every adopter saw 3 untracked files on first boot of `/ops-local-manager`, with `git add -A` risk on per-user friction logs. Driver: dogfooding finding `feedback/ops-local-manager-gitignore` from seat `ade-ops-1` (commit `5362b34`).

### Added — entry-point skills + autopilot

- `/seat` — local steward of the seat (boot snapshot + drift check + hand-off router). Generic generalisation of the legacy enterprise `/ops-local-manager`. Status: preview.
- `/ops-operator` — autopilot for chained end-to-end operations (migrate dev → cert → prod, deploy + run + publish + report). Plan → single approval → batch execute with mandatory safety hooks. Status: preview.

### Added — convention

- `core/conventions/distribution-evolution.md` — three scaling patterns (add project / fork affiliate / start clean) + decision tree + learning signals each pattern returns to the framework. Answers the "where do we activate new users?" question.
- `core/conventions/seat-triad.md` — new section "Seat modalities — operator vs canary" + soft (factory-reset) vs hard (fresh-install) reset.
- `core/conventions/seat.md` — fifth role `onboarding-canary` + "How roles affect operator skill behaviour" table.
- `core/conventions/powerbi-workflow-choice.md` — engine path vs MCP `powerbi` path decision tree.
- `core/conventions/credentials.md` — identifier-vs-secret distinction + DPAPI nuance + single/multi-workspace decision matrix + first-run discovery rule.

### Added — playbooks (moved from internal docs, now publishable)

- `core/playbooks/playwright-pbi-loop.md` — dedicated `--user-data-dir` pattern (Strategy A): eliminates kill-Edge-before-each-skill friction observed on legacy enterprise seats.
- `core/playbooks/pbir-gotchas.md` — PBIR rendering / deploy gotchas catalog referenced by `/pbir-create` and similar visual-loop skills.

### Added — Fabric workspace lifecycle suite (8 skills, F2)

- `/fabric-capacity-list`, `/fabric-workspace-create`, `/fabric-workspace-delete` (with safety hook), `/fabric-lakehouse-create`, `/fabric-pipeline-deploy`, `/fabric-pipeline-run`, `/fabric-pipeline-poll`, `/fabric-items-list`.

### Added — CLI subcommand + engine helpers

- `python -m core.cli pbir-create <name> --env <env> --spec <file>` — wrapper around `ReportBuilder.from_spec()` + Fabric REST deploy. Replaces the need to hand-write the build script (closes P1-B).
- `assess_notebooks_merged()` in `core/parsers/databricks_migration_assess.py` — merges `src/` + `state/{env}/notebooks/` for migration assessment when notebooks originate Fabric-side (closes P2-C).
- `core/platforms/databricks/sql_ingest_via_rest.py` — stdlib-only Databricks SQL Statement Execution REST helper for environments where JDBC + `%pip` are unavailable (Fabric Trial capacity). Includes `pull_table_via_rest()` iterator + `map_databricks_type_to_spark()` type mapping (closes P2-D + P3-B).

### Added — reference distribution

- `distributions/reference/projects/databricks-fabric-migration/src/notebooks/fabric/hydrate_lakehouse_from_databricks.py` — Fabric Spark notebook that reads gold via JDBC from external Databricks and writes Delta to the lakehouse (cross-cloud integration when Mirrored Catalog is unavailable).
- `distributions/reference/projects/databricks-fabric-migration/scripts/factory-reset.ps1` (soft) + `scripts/fresh-install.ps1` (hard) — canary-mode reset scripts.
- `_setup/create_demo_tables.py` enriched with `channel` (Online/Retail/Wholesale/B2B) + `region` (EMEA/Americas/APAC/LATAM) columns to satisfy TMDL mappings end-to-end.

### Fixed

- `core/connectors/fabric.py` (#20 closure, Fix A): drop item-type directory level from `local_rel`; state lays out symmetric to `src`.
- `core/engine/operations.py` (#20 closure, Fix B-3): diff state collection skips `_editor.*` and `*.pbip` — Power BI Desktop convenience stubs no longer surface as spurious "remote-only" entries.
- `.claude/commands/ops-{dev,prod,review}.md`: new Step 2.4 remote drift check (auto-fetch + behind/ahead/diverged surfacing). `/ops-prod` refuses to start if the seat is behind upstream (stale framework may miss safety fixes).
- `.claude/commands/ade-ops-onboarding.md`: new Step 3.5 MCP config + smoke test walks the operator through copying `.mcp.example.json` → `.mcp.json` and verifying each server is alive (closes P2-B).
- `dim_product.tmdl`: dropped 5 columns the gold notebook does not produce — TMDL aligned with `gold_dm_product` output (closes #22 full).

### Notes

The lab maintains `/ops-manager` as a single-operator framework-maintainer skill (intentionally not published). Consumer-side seats use the `/seat` + `/ops-operator` entry points + the role-confined `/ops-{dev,prod,review}` operative skills.

## [v0.2.0] — 2026-06-14

**Harness version bump 0.1.0 → 0.2.0** — the first release cut under the project's release-versioning model. Pre-1.0 (public preview — the consumer contract is not yet frozen).

### Added  `[compat:minor] [impact:additive]`

- **`ade-ops --version`** — the CLI now reads the harness version from a `core/VERSION` manifest (was a hardcoded literal), so every install reports a consistent version.

## [F1.x — 2026-05-28] Initial orphan release + multi-wave content

## [F1.x — 2026-05-28] Initial orphan release + multi-wave content

First public release using the orphan release model. The prior preview history has been replaced by a single snapshot. All the content shipped on 2026-05-28 (multiple lab waves: framework conventions, F2 Fabric suite, signup form, seat triad, credential rules, dogfooding-driven fixes) is consolidated here. Full provenance + author attribution lives in the lab private repo.

### Added — release model + governance

- **Orphan release model** (`core/engine/publish.py`, `core/cli/main.py`): `/ops-publish` now wipes the target dir before write by default and supports `--push <remote>` for one-shot force-push releases.
- **CONTRIBUTING.md** "Contributing to the public preview (orphan release model)" section documenting the contributor flow under the orphan model.

### Added — seat & identity

- **Seat convention** (`core/conventions/seat.md`): formal schema for the *(clone, distribution)* identity pair, role table (maintainer / primary-tester / contributor / observer), governance defaults, lifecycle. From ade-ops-2 dogfooding finding.
- **Seat triad** (`core/conventions/seat-triad.md`): identity / context / ops as three complementary layers; gitignored user-data partition that survives orphan releases. Drives the "release-channel mental model".
- **Topology model** (`core/conventions/topology-model.md`): three repository types (template / team / maintainer lab), three communication flows (intra-team / seat→template / template→seat), three identities a seat knows about itself, two bootstrap patterns. Lets any agent on any seat self-orient.
- **`/ops-session-close` skill + template** (`.claude/commands/ops-session-close.md` + `core/templates/seat-session.md`): structured session log per seat (goal / outcome / commits / findings / next entry point) for cross-session continuity.
- **Boot UX hook** in `/ops-dev`, `/ops-prod`, `/ops-review`: new Step 2.5 "Seat Triad — Load Identity, Context, Ops" surfaces continuity at session start.

### Added — Fabric workspace lifecycle (F2)

Eight new skills wrapping the Fabric REST API helpers already in `core/connectors/fabric.py`. All status: preview. Source patterns from the demo-claude `local/` ad-hoc scripts.

- `/fabric-capacity-list` — list available capacities (preflight for workspace create).
- `/fabric-workspace-create` — provision a new workspace with name-collision + capacity-state pre-flight.
- `/fabric-workspace-delete` — delete a workspace with **mandatory safety hook**: inventory + name double-check + final confirmation (encodes the "cleanup deletes workspace" gotcha from prior dogfooding).
- `/fabric-lakehouse-create` — provision a Lakehouse with SQL endpoint surfaced.
- `/fabric-pipeline-deploy` — Data Pipeline create / update with notebook name resolution.
- `/fabric-pipeline-run` — kick off a pipeline run with optional `--wait` chained to poll.
- `/fabric-pipeline-poll` — monitor a run to terminal state with activity-level error fetch on failure.
- `/fabric-items-list` — lightweight workspace inventory.

### Added — credentials handling

- **`core/conventions/credentials.md`** — canonical pattern documenting the two-level model (project-bound `credentials.yaml` `${VAR}` references vs user-bound env), the four Windows env-var modalities (inline / `setx` user-scope / `.claude/settings.local.json` env field / `$PROFILE`), and the **cross-seat conflict gotcha** (modality 2 leaks across seats on the same OS user). Includes the **first-run discovery rule**: when an agent encounters an unset credential, it asks, executes inline, proposes project-scoped persistence as default, logs `CREDENTIAL-DISCOVERED` to `ops.log`.
- **Anti-pattern guard**: project-bound credentials (DATABRICKS_*, FABRIC_*, POWERBI_*) MUST use modality 3, NEVER modality 2 — the convention explicitly warns and provides a remediation playbook.

### Added — community surface

- **`.mcp.example.json`** published as the canonical setup template for fresh clones, including the canonical names of the wrapped MCP servers (`databricks` → `databricks-mcp-server` from the Databricks AI Dev Kit; `powerbi` → Microsoft `analysis-services.powerbi-modeling-mcp`).
- **Private preview signup** issue form (`.github/ISSUE_TEMPLATE/private_preview_signup.yml`): structured fields (use case, scenario, team size, platforms, adoption stage, timing, contact preference). Explicit public-info caveat + ack checkbox. Linked from README.
- **Inter-agent consultation playbook** extended (`core/playbooks/inter-agent-consultation.md`) with Step 0.5 topology selection: 5-row decision tree for same-machine vs different-machine cross-seat dialogue.

### Fixed — engine

- **Pull writes via `write_bytes`** (`core/engine/operations.py`): prevents Windows from translating `\n` → `\r\n`, which was defeating the diff signal byte-by-byte after every pull on Windows.
- **CLI UTF-8 console** (`core/cli/__main__.py`): reconfigure stdout/stderr to utf-8 — prevents cp1252 Windows console crash on arrow characters in failure hints.
- **Push outcome granularity** (`core/engine/operations.py` + CLI): `push()` now returns a `PushResult` with pushed / total / failed_paths / outcome (`ok | fail | partial | empty`). The CLI logs the actual outcome to ops.log with detail `N/M — failed: K`, no more silent `ok` when partial failures occurred.
- **Fabric preflight** (`core/cli/main.py`): `_preflight_scope_credentials` now branches on `auth_method` (`az_cli` → `az_tenant_id`; `service_principal` → `tenant_id` + `client_id` + `client_secret`; `device_code` → `tenant_id`) instead of always checking `tenant_id` and emitting a misleading "set AZURE_TENANT_ID" hint.
- **Databricks host parameter** (`core/connectors/databricks.py`): `DatabricksConnector.from_credentials()` now accepts an explicit `host` arg sourced from `project.yaml`, removing the implicit dependency on `credentials.yaml` carrying the workspace URL (which is not a secret).
- **Non-strict overlay env resolution** (`core/engine/config.py`): `load_overlay()` resolves env vars with `strict=False` matching `load_credentials()`, so an unset variable scoped to one operation does not break unrelated scopes.

### Fixed — reference distribution

- **AcmeSales TMDL `<your-workspace-id>` placeholder** (`distributions/reference/projects/databricks-fabric-migration/overlays/dev.yaml`): added overlay transform that resolves the placeholder to `${FABRIC_WORKSPACE_DEV}` at deploy time. Closes the gap where operators with no replacement applied saw `<your-workspace-id>` in the deployed model connection string.

### Notes

- Multiple ade-ops-2 dogfooding findings were absorbed into the lab during the day (waves 1 + 2: seat convention, CLI fixes, host param, overlay strict, CRLF reinjection, TMDL placeholder). Each contributor commit is preserved in the lab private repo with full author attribution; the SHA on the public preview does not survive each release wipe by design.
- Two findings remain **open** (no fix yet): `fabric-diff-path-symmetry` (#20) and `tmdl-gold-schema-mismatch`. They are recorded under `docs/feedback/` on the lab side and will be addressed in a subsequent release.
- The `feedback/2026-05-27-crlf-reinjection` branch on the public preview has been removed after its content was absorbed.
