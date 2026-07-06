---
name: ops-feedback
description: Send Structured Feedback to the Framework Maintainers
---

# /ops-feedback — Send Structured Feedback to the Framework Maintainers

You are capturing a **structured feedback report** from a framework user back to the maintainers. Use this skill whenever the user (or you, working alongside the user) notices:

- **Outdated documentation** — the doc says X but the real state is Y
- **A bug** — something fails or behaves wrong
- **A missing feature** — a workflow step is not covered
- **A usability issue** — something works but is confusing, slow, or error-prone
- **Other** — anything worth surfacing that doesn't fit the above

The goal is **zero friction for the reporter, full context for the maintainer**. You ask 2–3 short questions, auto-capture environment context, and write a single file. The **submission channel adapts to access**: a pre-filled GitHub Issue for adopters on a public clone (the universal channel that reaches the maintainer without write access), or a commit + push for maintainers / client-DevOps teams who can write to the repo.

## Usage

```
/ops-feedback                              # interactive — ask for everything
/ops-feedback "short description"          # pre-fill description, ask the rest
/ops-feedback bug "short description"      # pre-fill type + description
```

`$ARGUMENTS` — optional: `[type] "description"`. Valid types: `bug`, `outdated-docs`, `missing-feature`, `usability`, `other`.

## Behavior

### Step 1 — Gather the essentials

Ask the user (skip any field already pre-filled via `$ARGUMENTS`):

1. **Type** — one of: `bug` / `outdated-docs` / `missing-feature` / `usability` / `other`
2. **Short description** — one line, the headline
3. **Detail** — multi-line: what happened, what was expected, where the gap is. Encourage the user to paste relevant output/snippets.
4. **Severity** *(optional, default `normal`)* — `blocker` / `high` / `normal` / `low`
5. **Proposed fix** *(optional)* — if the user has an idea, capture it

If a persona invoked this skill on the user's behalf (e.g. `/<client>-onboarding-agent` detected a gap), pre-fill **persona** = invoking persona's slug and explain to the user what is being reported, then confirm before writing.

### Step 2 — Auto-capture context

Without asking the user, gather:

- `date` — ISO date (e.g. `2026-05-18`)
- `branch` — `git rev-parse --abbrev-ref HEAD`
- `commit` — `git rev-parse --short HEAD`
- `cwd` — current working directory (absolute path)
- `project` — if cwd is inside a project (nearest `config/project.yaml`), record the project slug; else `null`
- `persona` — the active persona/skill if known (passed in or asked), else `null`
- `ops_log_tail` — last 10 lines of the project `ops.log` if one exists, else skip

### Step 3 — Write the file

Compute a slug from the short description: lowercase, ASCII only, words joined with `-`, max 6 words.

Target path:

- If the cwd is a project tree, write to `<repo_root>/docs/feedback/YYYY-MM-DD_<slug>.md` (where `<repo_root>` is the topmost git repo, not the project root).
- Otherwise write to `docs/feedback/YYYY-MM-DD_<slug>.md` relative to cwd.

If the file already exists (same slug same day), append `-2`, `-3`, ... until unique.

Use this template:

```markdown
---
date: 2026-05-18
type: outdated-docs
severity: normal
persona: <client>-onboarding-agent
status: open
project: <client>/<project>
branch: ade_ops
commit: a1b2c3d
cwd: <lab-root>
---

# {Short description}

## Detail

{Multi-line detail}

## Proposed fix

{Optional — leave blank if none}

## Auto-captured context

- **Date**: 2026-05-18
- **Persona**: <client>-onboarding-agent (or `null`)
- **Project**: <client>/<project> (or `null`)
- **Branch**: ade_ops
- **Commit**: a1b2c3d
- **Cwd**: <lab-root>

### Recent ops.log

```
{last 10 lines of project ops.log, or "(no ops.log found)"}
```
```

### Step 4 — Submit (the channel depends on write access)

First determine whether the reporter can write to the upstream repo. If `gh` is
installed and authenticated:

```
gh repo view --json nameWithOwner,viewerPermission
```

`viewerPermission` ∈ `ADMIN` / `MAINTAIN` / `WRITE` → **direct channel**;
`READ` / `NONE` (or `gh` unavailable / not authed) → **Issue channel**.

**Direct channel** (lab maintainer, client-DevOps team with write access):
show the written path + a one-line preview, then prompt:

> Feedback salvato in `{path}`. Lo committo e pusho adesso (consigliato per consegnarlo al manutentore), oppure preferisci dopo?

On yes, stage **only the new file** (`git add <path>`) and commit:

```
feedback({type}): {short description}
```

Push to the current branch's upstream. No upstream / detached HEAD → report it
and let the user decide. On no, leave the file unstaged and remind them how to
commit later.

**Issue channel** (external adopter on a public clone — the universal path that
reaches the maintainer without write access): a local commit would push nowhere
and **fail silently**, so **do not commit**. Keep the local `.md` as the
reporter's own record (untracked, no `git add`), and open a pre-filled GitHub
Issue with the `feedback.yml` template:

- `gh` authed → `gh issue create --repo <upstream> --title "{type}: {short description}" --body-file {path}`
- else → print a ready-to-click URL and ask the user to paste the detail:
  `https://github.com/<owner>/<repo>/issues/new?template=feedback.yml&title=<url-encoded "{type}: {short description}">`

Confirm to the user which channel was used and the resulting Issue URL (or local path).

## Safety

- **Never** read or transmit credentials. The auto-capture does not include `credentials.yaml` content nor environment variables.
- **Never** commit anything besides the new feedback file unless the user explicitly approves.
- **Never** push to `main` / `prod` branches without explicit confirmation. Default branches for feedback are working branches (`ade_ops`, feature branches, etc.).
- If the cwd is not a git repo, write the file to `feedback/YYYY-MM-DD_<slug>.md` under cwd and tell the user — no git operations.
- On a clone **without write access**, never rely on `git push` (it fails silently and the feedback never reaches the maintainer) — use the Issue channel.

## Why this exists

Framework users (<client> analytics team, future distributions) need a low-friction channel to surface gaps back to the maintainers. Email / chat is lossy and unstructured; opening a DevOps work item is high-friction. This skill captures the report **in-band** while the user is already in Claude Code, with full session context, and produces a versioned artifact that the maintainer can triage with `ls docs/feedback/`.

The persona side of the contract: any persona that detects "doc says X but probe shows Y" should proactively offer `/ops-feedback` — the user shouldn't have to remember it exists.

Issues filed via the Issue channel are harvested by the framework maintainer (ops-manager) into the lab's canonical `docs/feedback/` record — so an adopter's feedback survives even though the public repo is a release channel where orphan releases rewrite history.
