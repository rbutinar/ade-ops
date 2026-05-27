# Sanitization patterns for `/ops-publish`

> Documentation of the publish-time sanitization pipeline. Pattern *values*
> live in `_private_sanitization_values.yaml` (lab-only, gitignored). This
> file describes the *categories*, *behavior*, and *maintenance protocol*.
>
> Maintained by `ops-manager`. Last documentation revision: 2026-05-27.

## Why split structural vs literal

The engine consumes three categories of patterns (BLOCK / REPLACE / ALLOW)
to gate publish-time content. Earlier revisions kept the literal pattern
values in this file and self-exempted it from scanning so it could ship
verbatim. That approach leaked every literal value the file was designed
to block (the file itself becomes the index of sensitive tokens).

Current model: this file is **structural-only** — it documents categories,
behavior, and maintenance protocol, but contains no literal sensitive
values. The literal table lives in `_private_sanitization_values.yaml`
which is gitignored and never published. The engine self-exemption is
removed; both files can ship as-is because neither contains anything
that needs blocking.

## Categories

| Category | Action on match | Description |
|---|---|---|
| **BLOCK** | refuse publish, exit 1, log violation list | Patterns identifying sensitive content that must not leak |
| **REPLACE** | auto-substitute with placeholder, log replacement | Patterns with a known public equivalent (e.g. corporate name → `<organization>`) |
| **ALLOW** | positive assertion — pattern must be present in target | Required content in the published copy (e.g. author name in LICENSE) |

## Pattern shapes

The engine recognises these categorical shapes (instantiated as concrete
regex in `_private_sanitization_values.yaml`):

- **Identity tokens** — personal emails, service principal UPNs, named individuals
- **Path tokens** — workstation paths, local code roots, user profile paths
- **Tenant / workspace identifiers** — UUIDs, host names, tenant short-names
- **Client slugs** — client names, project codes, internal seat schemes
- **Naming conventions** — workspace naming patterns, schema prefixes
- **Organizational mentions in prose** — corporate names (REPLACE category, not BLOCK)
- **Required attributions** — author names, license markers, sample brand placeholders (ALLOW category)

## Scope and matching

A pattern can be scoped to specific file globs. Defaults to `**/*` (all
publishable files). Binary files (extensions outside the engine's text
allow-list) are byte-copied without scan. The REPLACE pass applies to
**all** text files including non-extensioned ones (`requirements.txt`,
`.gitattributes`, etc.) — earlier revisions used a narrow `.md/.py/.yaml`
allow-list which missed those.

## noqa exemption

If a BLOCK regex hits an unavoidable false positive (variable name, test
fixture, deny-list literal in engine code itself), exempt the line:

- Python / YAML: `# noqa: ade-ops-sanitize=<rule-name> reason="..."`
- Markdown: `<!-- noqa: ade-ops-sanitize=<rule-name> reason="..." -->`

Audit exemptions quarterly to verify they're still valid.

## Maintenance protocol

When a new sensitive value surfaces (feedback, incident, audit):

1. Add a rule to `_private_sanitization_values.yaml` under the correct category
2. Re-run `python -m core.cli publish --dry-run` to verify the rule catches the value
3. Update the rule's `last_updated` field
4. If the rule introduces a category not yet documented above, add a
   structural description here (without disclosing the literal value)

## Related

- `[[ade-ops-public-launch]]` — strategy and rationale for sanitization decisions
- Skill `/ops-publish` — consumer of this patterns library
- Engine: `core/engine/publish.py` — parser + applicator
- Lab-only sibling: `core/conventions/_private_sanitization_values.yaml`
