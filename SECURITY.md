# Security Policy

## Threat model

ade-ops is a local CLI + Claude Code agent. It runs on the operator's machine, with the operator's credentials, against remote workspaces the operator already controls. Calibrate findings against this model:

### Trusted inputs (NOT an attack surface)

- `config/project.yaml`, `overlays/*.yaml`, `patches/**` — authored by the operator. If an attacker can write here, they can edit any source file in the repo too; the threat is already lost.
- `config/credentials.yaml` and `${ENV_VAR}` references — provided by the operator, scoped to their session.
- CLI arguments and environment variables — operator-supplied.
- Tokens / PATs in memory during a session — operator owns them.
- The operator's own clone of the repo on disk.

Path traversal, "SQL injection" via table-name args, or YAML "tampering" through these channels is out of scope: the operator IS the controller of these inputs.

### Untrusted inputs (REAL attack surface)

- Content pulled from a remote workspace into `state/` — notebooks, semantic-model TMDL, pipeline JSON. A compromised workspace could return crafted payloads that flow into Claude's context (prompt injection) or into local file paths (zip-slip-style if archives are ever extracted).
- Third-party MCP servers configured via `.mcp.json` — they run with the operator's privileges and see the conversation transcript.
- Shared overlays / patches contributed by other operators on the same distribution (multi-operator teams). Treat as "untrusted code review required" before push.
- Notebook output cells pulled from a workspace and rendered to the operator — could contain misleading instructions for the agent.

### Out of scope

- DoS, resource exhaustion, missing rate limits.
- Operator's own machine compromise (if the laptop is owned, the game is over).
- The operator running ade-ops against a workspace they don't own — that's a process / authorization issue, not a code issue.

Findings should map to one of the "untrusted inputs" rows above, or they're likely false positives.

## Reporting a vulnerability or data leakage

**Do NOT open public issues, pull requests, or discussions for security vulnerabilities or data leakage.**

ade-ops is sanitized before publication, but the pipeline is not infallible. If you spot any of the following on the public tree:

- Hardcoded credentials, tokens, or secrets
- Client/customer names, internal project codes, or internal hostnames that should have been redacted
- An exploitable vulnerability in the engine, connectors, or skill bodies

…please report it through **GitHub Private Vulnerability Reporting**. Reports are encrypted in transit and at rest, visible only to maintainers, and never appear in `git log` or in any mirror.

### How to report

**Via UI** (recommended):

1. Open the [Security tab](https://github.com/rbutinar/ade-ops/security/advisories/new)
2. Fill in **summary**, **description**, and **severity**
3. Submit the draft advisory

**Via `gh` CLI**:

```bash
gh api repos/rbutinar/ade-ops/security-advisories \
  --method POST \
  --field summary="<short title>" \
  --field description="<details, reproduction, suggested fix>" \
  --field severity="low|medium|high|critical"
```

### What to expect

- Maintainers acknowledge the report within 5 business days
- Triage and fix are tracked privately on the advisory thread
- Public disclosure happens only after mitigation (sanitization-rule update, credential rotation, engine patch, etc.)
- Reporter is credited in the advisory, unless they request anonymity

### Out of scope

Non-security feedback (bugs, friction, gaps in skills/docs) belongs in the public issue tracker via the standard issue templates, or via the `/ops-feedback` skill if you are running ade-ops locally.
