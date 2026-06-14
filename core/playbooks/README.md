# core/playbooks — Framework operational playbooks

Procedural how-to guides for **operations that any agent in the framework
may need to perform**. Distinct from `core/docs/` (which is descriptive
reference — *"what is X"*) — these are **prescriptive procedures**
(*"how do you do X step by step"*).

## When to add a new playbook

When a procedure:

1. Recurs across multiple skills or distributions (not skill-specific)
2. Has well-defined steps that benefit from being followed in order
3. Has tradeoffs / failure modes that need to be surfaced once, not
   re-discovered each time
4. Is invoked **autonomously by agents** (not just by humans)

If only one skill ever uses the procedure, keep it in the skill body.
If only humans run it, it belongs in `docs/` (project docs) or a distribution-level
playbook (`distributions/{client}/docs/playbook/`). `core/playbooks/` is
specifically for cross-distribution, agent-invokable procedures.

## Naming convention

`{verb}-{noun}.md` — imperative, since these are how-to:

- `inter-agent-consultation.md`
- `feedback-triage.md` *(future)*
- `skill-promotion-evaluation.md` *(future)*
- `session-close-protocol.md` *(future)*

## Structure convention

Each playbook should have:

1. **When to invoke** — explicit trigger conditions
2. **Decision tree** — if applicable (e.g. handoff vs dialogue)
3. **Step-by-step procedure** — numbered, with concrete examples
4. **Costs and tradeoffs** — make the price explicit so the agent can decide
5. **When NOT to use** — anti-patterns and better alternatives
6. **Templates / snippets** — copyable boilerplate where useful

## Consumed by

Skills cite playbooks in their body with a short pointer like:

> *"At startup, if you need to consult another agent in autonomia,
> follow `core/playbooks/inter-agent-consultation.md`."*

The pointer keeps skill bodies short; the playbook centralizes the
procedure for maintenance and evolution.

## Current playbooks

- [`inter-agent-consultation.md`](inter-agent-consultation.md) — how to
  consult another agent for a POV or technical input without user
  orchestration (thread-file pattern, status: working but costly until
  `SendMessage` is exposed by the harness)
