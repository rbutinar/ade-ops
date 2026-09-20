# Session — {{ session_date }} — {{ topic }}

> Template for a per-seat session log. Stored gitignored at
> `distributions/<dist>/.seat-sessions/{{ session_date }}_{{ topic_slug }}.md`.
> Generated/maintained by `/ops-session-close` (and read at boot by
> operator skills like `/ops-dev` to surface continuity).

**Seat**: {{ seat_name }} (`{{ clone_path_basename }}`)
**Distribution**: {{ distribution_slug }}
**Operator**: {{ operator }} ({{ role }})
**Started**: {{ started_at_iso }}
**Closed**: {{ closed_at_iso }}
**Duration**: {{ duration_human }}

---

## Goal

> One sentence: what was this session about?

{{ goal }}

## Outcome

> Was the goal achieved? Partial / blocked? One paragraph.

{{ outcome }}

## Commits shipped

> One bullet per commit landed in the session. Include short SHA, repo
> (lab vs DevOps vs public-preview), and one-liner. If the session
> shipped no commits, write `(none)`.

{{ commits_block }}

## Findings opened

> Findings filed during the session that remain open. Cross-reference
> the `/ops-feedback` file path or task ID. If none, write `(none)`.

{{ findings_block }}

## State at session close

> What is left dirty / pending? Working tree status, waiting on whom,
> blocker descriptions. Concrete enough to resume without re-deriving.

{{ state_block }}

## Next session — entry point

> Single paragraph: when an operator (human or agent) opens this seat
> next, what should they do *first*? Quote the exact command, file, or
> task. This section makes the seat resumable.

{{ next_entry_point }}

---

<!--
Frontmatter for tooling. Do not delete — the boot UX reads these keys
to surface a one-line summary at seat open.
-->

```yaml
session_id: {{ session_date }}_{{ topic_slug }}
status: closed                 # in_progress | closed | abandoned
unresolved_findings: {{ unresolved_count }}
unresolved_tasks: {{ unresolved_tasks_count }}
last_commit_sha: {{ last_commit_sha }}
next_owner: {{ next_owner }}   # seat name or "any" for unassigned
```
