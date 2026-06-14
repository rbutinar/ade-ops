# Convention: `ops.log` operations log

Operative skills append one line per infrastructure operation to the project
`ops.log`. The log is an **audit record**: it states which role acted, with
which gates, on which environment, and whether it succeeded.

## What belongs in the committed log — and what doesn't

`ops.log` can serve **two different kinds of audit**, and conflating them is what makes a
committed log painful in multi-seat operation:

- **Team-durable** — deploys, prod/destructive ops, decisions, who-changed-the-deliverable.
  Wants to be **committed, structured, queryable, low-churn**.
- **Personal-ephemeral** — dev iterations, reads, investigations, failed attempts; the
  moment-by-moment journal. High-frequency, per-user, mostly **no-commit**.

**Route by KIND, not by file.** Committed shared history is for the team-durable kind; the
personal-ephemeral kind belongs in a **gitignored, per-clone** journal. `merge=union` +
atomic append (`core/oplog`) are the *mechanics* that make a committed log survivable —
**not** a license to commit ephemeral per-user noise.

### Should *this* distribution commit its `ops.log`? — the redundancy test

Commit it **iff no better committed, structured channel already holds the team-durable
slice.** If one does, the committed `ops.log` is redundant noise → demote to a gitignored
personal journal and route the durable slice to that channel.

| Distribution | Redundant durable channel already committed? | Outcome |
|---|---|---|
| **A client delivery distribution** | **Yes** — a committed `team-log.md` + git trailers + `state/{cert,prod}/` mirrors + a PM activity model | **Demote** → gitignored personal journal; durable audit via those channels. `oplog` still serves the local journal's write-race. |
| **Lab** (this repo) | **No** — `CONTEXT.md` is curated/lossy (not the raw append-only audit); trailers cover only *committing* ops, not the no-commit ones | **Keep committed** + `union`/`oplog` + discipline: pure per-session scratch → `local/` (gitignored), not `ops.log`. |

The lab is **not exempt** from the principle — it keeps a committed `ops.log` *only because
it is non-redundant* (the sole committed, raw, chronological record, incl. no-commit
operations). Grow a redundant durable channel (a lab `team-log.md`, or a formalized
`CONTEXT.md`) and the same test demotes it too.

## Line format

```
{ISO_timestamp} | {role} | {ACTION} | {env|--} | {detail} | {ok|fail}
```

| Field | Meaning |
|---|---|
| `ISO_timestamp` | `YYYY-MM-DDTHH:MMZ` (**UTC**) |
| `role` | the persona slug **actually active** — see the honesty rule below |
| `ACTION` | operation verb (`PULL`, `PUSH`, `DEPLOY-RAW`, `PBI-PUBLISH`, …) |
| `env` | target environment (`dev`/`cert`/`prod`) or `--` if not env-scoped |
| `detail` | scope + outcome counts, skill-specific |
| `ok`/`fail` | terminal status |

## Role-slug honesty rule

`{role}` records **which role actually operated**, because the slug is how a
reader knows which role's safety gates were in force. Therefore:

- If you are operating **inside a persona** (`/ops-dev`, `/ops-prod`,
  `/ops-operator`, `/ops-review`, `/ops-manager`, `ddf-operator`, …), log under
  **that** persona's slug.
- If you are operating **without a persona** — bare Claude invoking task skills
  directly — log as **`claude-adhoc`**.
- **Never** write a persona slug you are not operating as. A forged slug (e.g. a
  bare session writing `ops-dev`) produces a **false audit trail**: the log
  asserts that role's gates applied when they did not. This is an integrity
  defect, not a cosmetic one.

When in doubt, `claude-adhoc` is always the honest choice over an invented
persona name.

## Writing the log — append-only, **never** Edit

`ops.log` is **append-only**. Do **not** open it with a match-and-replace editor
(`Edit` / `sed -i` / IDE find-replace): a read-modify-write on a file another live
session is appending **races** ("file modified since read") and can clobber or
interleave. Append instead — **atomically**:

```
python -m core.oplog --role ops-manager --action ADD --scope docs \
  --detail "what happened + outcome counts" [--outcome done] [--log PATH]
```

`core/oplog.py` does a **single `O_APPEND` write** (no read-modify-write → no race) and
formats the 6 fields by construction; it finds `docs/ops.log` upward from the cwd unless
`--log` is given. A raw `>> docs/ops.log` append is the manual fallback (also race-free;
the format is then on you). The helper enforces **format + atomicity**, not the
**role-slug honesty** rule above — `--role` is your honest assertion.

**Why not a folder of per-entry files?** Because `ops.log` is **git-tracked**
(`merge=union` merges concurrent commits) **and read as a stream** (`tail`, boot). The
per-file shape is right on a **non-merge substrate** (OneDrive sync → conflict-copies,
e.g. `core/fleet`), but here it would regress the read for no gain. **Substrate follows
the access pattern.**

> **Kinship / propagation:** this atomic append and `core/fleet`'s `write_json_atomic`
> are one idea — *make conflict-freedom structural at the write path* — in two shapes.
> Future: a shared `core` io-util; and a cross-clone fleet **event log**, if it ever
> exists, uses the **folder** shape (OneDrive), not single-file append. Same
> agent-communication-hardening thread (TICK-017).
