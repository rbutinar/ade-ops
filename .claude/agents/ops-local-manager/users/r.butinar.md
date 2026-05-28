---
handle: r.butinar
display_name: Roberto Butinar
graduation_date: 2026-05-21
last_sync_head: fce31d9
last_personas:
  - /seat
  - /ops-local-manager
  - /ops-session-close
  - /ops-manager
open_drafts: []
hints_to_try:
  - Lab clone is the workshop — /ops-local-manager itself is iterated here; downstream distros consume it.
  - CONTEXT.md / IDENTITY.md bootstrapped 2026-05-28 — not yet covered by .gitignore (verify pattern).
---

## Friction log

- 2026-05-28 — bootstrap di CONTEXT.md/IDENTITY.md crea due file `??` in git status; verificare pattern in `.gitignore` per `.claude/agents/ops-local-manager/{CONTEXT,IDENTITY,users/}.md`.

## Notes

- Roberto è il framework maintainer (lab clone = workshop). Per il lab, `/seat` è normalmente sufficiente; `/ops-local-manager` viene esercitato qui per dogfood / iterazione UX.
- Distribution propagation: lab è meta-distribuzione (workshop + lab-distribution). Vedi memory `project_distribution_propagation_rules`.
