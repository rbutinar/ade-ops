---
date: 2026-05-28
type: missing-feature
severity: normal
persona: ops-local-manager
status: open
project: null
branch: feedback/threat-model-section
commit: 5362b34
cwd: C:\codebase\ade-ops-1
---

# Add threat-model section to SECURITY.md

## Detail

Running `/security-review` against the freshly-public `ade-ops` clone today
(HEAD `5362b34`, repo wiped of customer IP) produced two HIGH-severity
findings that turned out to be false positives once the trust model was
made explicit during verification:

1. **"SQL injection" via `source_table`**
   (`core/platforms/databricks/sql_ingest_via_rest.py:135`,
   `statement = f"SELECT * FROM {source_table}"`). The reviewer treated
   `source_table` as untrusted input; in reality it's a CLI/library
   argument supplied by the operator to query their own warehouse with
   their own PAT. The operator IS the controller of the input.

2. **"Path traversal" via `overlay:` field**
   (`core/engine/config.py:97-98, 139-140`, `rel = env_cfg.get("overlay", ...)`
   then `self.root / rel`). The reviewer treated `project.yaml` as
   potentially attacker-controlled. In reality `project.yaml` is the
   operator's own config file; if an attacker can write there, they can
   edit any source file in the repo anyway. YAML is loaded with
   `yaml.safe_load`, so no deserialization risk.

Both findings consumed verification round-trips that would have been
avoided if `SECURITY.md` declared the trust boundary explicitly. The
issue is generic — `ade-ops` is a local CLI + Claude Code agent running
with the operator's credentials against the operator's own infra. Any
auditor (human or LLM) defaulting to a SaaS / multi-tenant threat model
will mis-categorize operator-supplied inputs as attack surface.

This is a missing-feature, not a bug: `SECURITY.md` ships clean and
correct, but it lacks a section that calibrates reviewers and contributors
on what to consider in scope vs out of scope.

## Proposed fix

Add a `## Threat model` section to `SECURITY.md` (or promote to
`docs/threat-model.md` if it grows). Draft below — kept inline so the
maintainer can edit in place.

```markdown
## Threat model

ade-ops is a local CLI + Claude Code agent. It runs on the operator's
machine, with the operator's credentials, against remote workspaces the
operator already controls. Treat findings against this model:

### Trusted inputs (NOT an attack surface)
- `config/project.yaml`, `overlays/*.yaml`, `patches/**` — authored by
  the operator. If an attacker can write here, they can edit any source
  file in the repo too; the threat is already lost.
- `config/credentials.yaml` and `${ENV_VAR}` references — provided by
  the operator, scoped to their session.
- CLI arguments and environment variables — operator-supplied.
- Tokens / PATs in memory during a session — operator owns them.
- The operator's own clone of the repo on disk.

Path traversal, "SQL injection" via table-name args, or YAML "tampering"
through these channels is out of scope: the operator IS the controller
of these inputs.

### Untrusted inputs (REAL attack surface)
- Content pulled from a remote workspace into `state/` — notebooks,
  semantic-model TMDL, pipeline JSON. A compromised workspace could
  return crafted payloads that flow into Claude's context (prompt
  injection) or into local file paths (zip-slip-style if archives are
  ever extracted).
- Third-party MCP servers configured via `.mcp.json` — they run with
  the operator's privileges and see the conversation transcript.
- Shared overlays / patches contributed by other operators on the same
  distribution (multi-operator teams). Treat as "untrusted code review
  required" before push.
- Notebook output cells pulled from a workspace and rendered to the
  operator — could contain misleading instructions for the agent.

### Out of scope
- DoS, resource exhaustion, missing rate limits.
- Operator's own machine compromise (if the laptop is owned, the game
  is over).
- The operator running ade-ops against a workspace they don't own —
  that's a process / authorization issue, not a code issue.

Findings should map to one of the "untrusted inputs" rows above, or
they're likely false positives.
```

Suggested location: insert as a top-level section in `SECURITY.md`,
above the existing redaction / sanitization material. Cross-link from
`README.md` "Security" mention and from `core/conventions/sanitization-patterns.md`.

## Auto-captured context

- **Date**: 2026-05-28
- **Persona**: ops-local-manager
- **Project**: null (cwd is repo root, not inside a project tree)
- **Branch**: feedback/threat-model-section
- **Commit**: 5362b34
- **Cwd**: C:\codebase\ade-ops-1

### Recent ops.log

```
(no ops.log found — cwd is not inside a project tree)
```
