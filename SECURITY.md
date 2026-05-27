# Security Policy

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
