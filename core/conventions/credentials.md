# Credentials — canonical pattern

> How an ade-ops seat handles secrets and environment variables across
> sessions, with the **first-run discovery rule** that turns one-time
> friction into automatic future-proofing.
>
> Documented 2026-05-28 after the ade-ops-2 PowerShell env-var
> persistence question + Roberto's framing "the agent should set them
> for next time, or ask the user to do so".

## Two-level model

Secrets and configuration values fall into two classes — each with a
different home. Mixing them is the most common source of bugs.

| Class | Examples | Lives in | Scope | Survives reset/orphan? |
|---|---|---|---|---|
| **Project-bound** | Databricks PAT, Fabric service principal client_secret, workspace ids, tenant ids the project needs | `config/credentials.yaml` (gitignored) of each project + references `${ENV_VAR}` for the value | Per-project | Yes (gitignored, lives in seat) |
| **Skill / MCP / API-bound** | OpenAI API key, Typefully token, GitHub PAT for gh CLI, MCP server bearer tokens | Windows / OS environment variables (user-scope) | Cross-project, per-user | Yes (registry user-scope) |

The principle: a value is **project-bound** if multiple operators on the
same project would use the same value (e.g. a service principal that
owns the Fabric workspace). It is **user-bound** if each operator has
their own copy (e.g. each operator's personal OpenAI key).

## Where the YAML file lives

```
distributions/<dist>/projects/<project>/config/credentials.yaml      # real, gitignored
distributions/<dist>/projects/<project>/config/credentials.example.yaml   # committed template
```

Inside `credentials.yaml` values can be literal OR reference an env var:

```yaml
databricks:
  host: ${DATABRICKS_HOST}        # resolved from process env
  token: ${DATABRICKS_TOKEN}      # resolved from process env

fabric:
  tenant_id: ${FABRIC_TENANT_ID}
  auth_method: az_cli
```

The engine reads these at operation time. Unresolved `${...}` literals
get surfaced by connectors as precise errors when the missing variable
is needed for the current scope (see `core/engine/config.py`
`load_credentials(strict=False)` + `load_overlay(strict=False)`).

## Setting environment variables on Windows — five modalities

| # | Modality | In-process effect | Persists after restart? | Encrypted at rest? | Best for |
|---|---|---|---|---|---|
| 1 | `$env:VAR = "value"; <command>` in PowerShell | ✅ for that command only | ❌ | n/a (volatile) | One-shot operations; ephemeral debugging |
| 2 | `setx VAR "value"` + close all terminals + relaunch Claude Code | ✅ (after restart) | ✅ user-scope registry | ✅ DPAPI-encrypted (HKCU\Environment) | Secrets on a single-workspace setup; user-scoped values |
| 3 | `.claude/settings.local.json` with `"env": {"VAR": "value"}` + restart | ✅ (after restart) | ✅ project-scoped (gitignored) | ❌ plain text on disk | Identifiers that vary per seat (multi-workspace setups) |
| 4 | `$PROFILE` PowerShell file (`$env:VAR = "..."` line) | ✅ for new shells | ✅ user-scope | ❌ plain text in `$PROFILE` | Vars consumed by many tools beyond Claude, like az CLI |
| 5 | Windows Credential Manager via Python `keyring` library | ✅ (read at use time) | ✅ per-key | ✅ DPAPI-encrypted | High-sensitivity secrets in multi-workspace setups (advanced, requires keyring lib) |

### Identifier vs secret — the key distinction

Before picking a modality, classify the variable:

- **Identifier** — workspace URL / id, tenant id, client id, file path,
  environment label. Low-to-medium sensitivity. Trapassed values are
  informational, not "weapons". Examples: `DATABRICKS_HOST`,
  `FABRIC_WORKSPACE_DEV`, `FABRIC_TENANT_ID`, `FABRIC_CLIENT_ID`,
  `POWERBI_WORKSPACE_ID`, `DEMO_USER_EMAIL`.
- **Secret** — token, password, client secret, API key. High
  sensitivity. Trapassed values can be used to impersonate. Examples:
  `DATABRICKS_TOKEN`, `FABRIC_CLIENT_SECRET`, `OPENAI_API_KEY`,
  `TYPEFULLY_API_KEY`, `GH_TOKEN`.

This classification drives the modality choice — see decision tree below.

### Why setx (modality 2) is more secure than settings.local.json (modality 3) at rest

Windows `setx` writes to the registry under `HKEY_CURRENT_USER\Environment`,
which is **DPAPI-encrypted** with a key derived from the OS user's login
credentials. An attacker with filesystem read but no login session cannot
recover the value.

`.claude/settings.local.json` writes plain text JSON to disk. The file is
gitignored (will not leak to remotes), but any process on the machine
with read permission on that file can read the value verbatim.

Trade-off: modality 3 is safer against *cross-seat conflict* (it scopes
per-project), modality 2 is safer against *at-rest disclosure on disk*
(it scopes per-user with encryption). The right choice depends on which
risk is dominant — see decision matrix.

### ⚠️ Cross-seat conflict — the user-scope leak gotcha

User-scope env vars (modality 2 via `setx`, or modality 4 via `$PROFILE`)
are **shared across every process the OS user runs on this machine** —
including every Claude Code seat on every repo. If you set
`DATABRICKS_HOST` via `setx` for one seat (e.g. a personal sandbox), a
different seat (e.g. a client project) on the **same Windows user** sees
the same value when its Claude Code restarts.

Concrete failure mode (observed 2026-05-28 in a real multi-seat setup):

1. Seat A runs on personal Databricks workspace `dbc-personal-...`.
   Operator runs `setx DATABRICKS_HOST "https://dbc-personal-..."`
   (modality 2) to persist credentials for that seat.
2. Operator opens seat B (client project, different workspace
   `adb-client-...`). The `~/.databrickscfg [client-profile]` is
   correctly configured.
3. Seat B invokes a `databricks` CLI command with
   `--profile client-profile`. The CLI precedence rules **prefer env
   vars over profile**: `DATABRICKS_HOST` wins. All traffic goes to the
   wrong workspace and the operation fails with confusing 404 /
   "not found" errors.

### Decision matrix — which modality for which variable

| Setup type | Variable type | Recommended modality | Why |
|---|---|---|---|
| Single-workspace seat (same value across all your seats on this machine) | Identifier (HOST, WORKSPACE_*, TENANT_ID, CLIENT_ID) | **2** (`setx` user-scope) | DPAPI-encrypted at rest, single value desired, zero conflict |
| Single-workspace seat | Secret (TOKEN, CLIENT_SECRET, API_KEY) | **2** (`setx` user-scope) | DPAPI-encrypted, no leak risk, no cross-seat issue |
| Multi-workspace seats on same machine (e.g. personal + client) | Identifier (HOST, WORKSPACE_*) — VARIES per seat | **3** (`.claude/settings.local.json` env field per seat) | Project-scoped, resolves cross-seat conflict, identifier sensitivity tolerates plain text |
| Multi-workspace seats | Secret (TOKEN, CLIENT_SECRET) — VARIES per seat | **5** (keyring → Credential Manager) preferred, **3** as trade-off | Keep DPAPI encryption + per-seat scoping; fall back to modality 3 only if accepting plain-text-on-disk risk for the value |
| Cross-project user secret (same key for all your projects) | Secret (OPENAI_API_KEY, GH_TOKEN, EDITOR) | **2** (`setx` user-scope) | DPAPI-encrypted, single value across all projects is desired |

### Single-workspace vs multi-workspace — how to know which one you are

- **Single-workspace setup**: all your seats on this machine target the
  same workspace (e.g. you have one Databricks workspace and N seats
  all point to it). Modality 2 user-scope is fine — same `setx` value
  works for everyone, and DPAPI keeps the secret encrypted.
- **Multi-workspace setup**: you have seats targeting different
  workspaces / tenants / clients on the same OS user. Each seat needs
  different identifier values. Modality 2 cannot help — only one user-
  scope value at a time. Use modality 3 for identifiers and modality 5
  (or 3 with trade-off) for secrets.

### Modality 5 — Windows Credential Manager via keyring (advanced)

For high-sensitivity secrets in multi-workspace setups, the Python
`keyring` library wraps Windows Credential Manager (DPAPI-encrypted,
per-key access control):

```python
import keyring
keyring.set_password("ade-ops-databricks", "<seat-name>", "<token>")
# later in code:
token = keyring.get_password("ade-ops-databricks", "<seat-name>")
```

Reads happen at use time (no `process.env` injection), so per-seat
isolation is automatic. The `credentials.yaml` `${VAR}` reference is
replaced by a `${KEYRING:service/key}` reference (engine-side feature,
backlog item for V2).

**Status**: not yet wired in the engine — backlog F2.x candidate. Use
modality 2 or 3 in the meantime based on the trade-off you accept.

### ⚠️ Cross-seat conflict — the user-scope leak gotcha

User-scope env vars (modality 2 via `setx`, or modality 4 via `$PROFILE`)
are **shared across every process the OS user runs on this machine** —
including every Claude Code seat on every repo. If you set
`DATABRICKS_HOST` via `setx` for one seat (e.g. a personal sandbox), a
different seat (e.g. a client project) on the **same Windows user** sees
the same value when its Claude Code restarts.

Concrete failure mode (observed 2026-05-28 in a real multi-seat setup):

1. Seat A runs on personal Databricks workspace `dbc-personal-...`.
   Operator runs `setx DATABRICKS_HOST "https://dbc-personal-..."`
   (modality 2) to persist credentials for that seat.
2. Operator opens seat B (client project, different workspace
   `adb-client-...`). The `~/.databrickscfg [client-profile]` is
   correctly configured.
3. Seat B invokes a `databricks` CLI command with
   `--profile client-profile`. The CLI precedence rules **prefer env
   vars over profile**: `DATABRICKS_HOST` wins. All traffic goes to the
   wrong workspace and the operation fails with confusing 404 /
   "not found" errors.

### Remediation when a modality choice has leaked or conflicts

Two distinct remediation scenarios:

**Scenario A — multi-workspace identifier leak** (most common, observed 2026-05-28):

You have a user-scope `DATABRICKS_HOST` set via `setx` for one workspace,
and now another seat on the same machine needs a different value. Migrate
the identifier (not the secret) to modality 3 per seat:

```powershell
# 1. Unset the user-scope identifier
setx DATABRICKS_HOST ""

# 2. For each seat, add to <seat-repo>/.claude/settings.local.json:
#    {
#      "env": {
#        "DATABRICKS_HOST": "<this seat's workspace URL>"
#      }
#    }

# 3. Keep DATABRICKS_TOKEN in user-scope (modality 2) IF both seats use
#    the same token. If they use different tokens, the next session
#    needs to switch token via setx-and-restart (workflow cost) OR
#    migrate the secret to modality 3 OR (best) modality 5 keyring.

# 4. Restart Claude Code in each seat.
```

**Scenario B — multi-workspace secret conflict** (cross-tenant tokens):

Each seat needs a different `DATABRICKS_TOKEN`. Modality 2 cannot hold
two values. Choose:

- **Modality 5 (preferred)**: store each token under
  `keyring.set_password("ade-ops-databricks", "<seat-name>", "<token>")`,
  read at use time. Engine support coming in V2 — meanwhile use a
  pre-flight Python snippet in the skill body to inject into `process.env`.
- **Modality 3 (trade-off)**: write the token literally in
  `.claude/settings.local.json` per seat. Trade-off: plain text on disk
  (gitignored but not encrypted). Accept this only for low-sensitivity
  tokens (e.g. Databricks Community Edition personal token) or where
  the file is on an encrypted disk + isolated OS user.

**In-flight workaround** (any scenario, no restart):

```powershell
$env:DATABRICKS_HOST = "<correct value for this seat>"
$env:DATABRICKS_TOKEN = "<correct token>"
<the actual command>
```

Or pass `--host` / `--token` flags explicitly to the CLI; flags have
highest precedence in most tool hierarchies.

### Why no in-process injection from another shell

Windows env vars are read once at process start. `setx` updates the
registry user scope but the already-running Claude Code parent does not
re-evaluate. Restarting Claude Code is the only path to inject a new
persistent value into its `process.env`.

POSIX systems (macOS/Linux) have the same constraint: a running process
sees only its own snapshot of the parent shell's env at fork time.

## First-run discovery rule (2026-05-28)

When an agent (or operator skill) encounters a credential value
**not yet configured** during the natural course of an operation, it
must follow this protocol — not silently ask the user every time:

### Step 1 — Surface the gap

> "Operation `X` needs `DATABRICKS_TOKEN` and I don't see it in the
> environment or in `credentials.yaml`. Provide a value? (paste it, or
> type 'skip' to abort)"

### Step 2 — Execute the current operation

Use modality 1 inline:

```powershell
$env:DATABRICKS_TOKEN = "<value just received>"; <the actual command>
```

The variable is available for the duration of this single Bash
invocation — sufficient for the current operation. Nothing yet
persists.

### Step 3 — Propose persistence (mandatory)

The agent classifies the variable (identifier vs secret) and the setup
(single-workspace vs multi-workspace), then proposes the right modality.

**Classification heuristic** (the agent uses name pattern + value shape):

- `*_HOST`, `*_WORKSPACE_*`, `*_TENANT_ID`, `*_CLIENT_ID`, `*_USER_PATH`,
  `*_USER_EMAIL` → **identifier**
- `*_TOKEN`, `*_SECRET`, `*_API_KEY`, `*_PASSWORD`, `*_PAT` → **secret**

**Setup detection**: the agent reads `.seat.yaml` of the current seat
plus any sibling seats it can see on the machine (`<dev-root>/ade-ops-*`,
`<dev-root>/<other client>-*`). If sibling seats target different
workspaces / tenants → multi-workspace setup. Otherwise single-workspace.

**Per-class recommendations**:

> "✅ Operation completed. The value I just used is **not persisted** —
> next session it will be gone.
>
> Classification: this is a **{identifier|secret}** in a
> **{single|multi}-workspace** setup.
>
> Recommended modality: **{2|3|5}**.
>
> {Specific proposal — one of these three forms:}
>
> ### If identifier in single-workspace setup → modality 2
> Run in PowerShell, close all terminals + Claude Code, relaunch:
> ```powershell
> setx DATABRICKS_HOST "<value>"
> ```
> Stored DPAPI-encrypted, same value across all your seats (which is
> what you want in this setup).
>
> ### If identifier in multi-workspace setup → modality 3
> Add to `<this seat>/.claude/settings.local.json`:
> ```json
> {"env": {"DATABRICKS_HOST": "<value>"}}
> ```
> Restart Claude Code. Per-seat scoped — no leak to sibling seats.
> Plain text on disk acceptable because this is an identifier, not a
> secret.
>
> ### If secret → modality 2 if single-workspace, modality 5 (or 3 trade-off) if multi
> - Single-workspace: `setx DATABRICKS_TOKEN "<value>"` + restart. DPAPI-
>   encrypted.
> - Multi-workspace: ideally Windows Credential Manager via `keyring`
>   (modality 5, engine support pending in V2). Trade-off until then:
>   add to `.claude/settings.local.json` env field (modality 3) —
>   accept plain-text-on-disk for the value.
>
> Or **skip** — accept that next session will prompt again."

The agent SHOULD walk the operator through the classification + setup
detection explicitly, not silently apply a default. Two seats on the
same OS user with conflicting needs is the failure mode the
classification is designed to surface.

The agent does NOT auto-write modality 1's value into modality 2 or 3
without explicit user confirmation. Two reasons: (a) it is the
operator's secret to manage, not the agent's; (b) the operator may
want this token to NOT survive (e.g. a one-shot debug token from a
sandbox account).

### Step 4 — Log the discovery

Regardless of the operator's choice in Step 3:

```
{ISO8601} | {role} | CREDENTIAL-DISCOVERED | - | - : var=<VAR_NAME> persisted=<yes|no|skip> | ok
```

This makes the audit trail self-evident: future sessions can scan
`ops.log` for past discovery events and pre-empt the prompt.

## Anti-patterns

- **Inlining real tokens in the skill body or in `credentials.example.yaml`** — these files are committed. Use `${ENV_VAR}` reference exclusively.
- **Hardcoding the token in a one-off Python script and forgetting it** — the script may live in `local/` (gitignored) but a stray `git add` exposes it. Use the env var indirection even for one-shots.
- **Running `setx` automatically without user confirmation** — silent persistence of a secret is a security regression. The first-run discovery rule mandates explicit consent at Step 3.
- **Asking for the same credential every session** — that is the failure mode the first-run discovery rule is designed to prevent. If you find yourself prompting for `X` more than once across sessions, escalate to "should we persist this?".

## Related

- [`seat-triad.md`](./seat-triad.md) — credential discovery events land in the ops layer (per-project `ops.log`)
- [`seat.md`](./seat.md) — identities in the `.seat.yaml` manifest are *static identity* (UPN, tenant), distinct from *secrets* (tokens) — the manifest never contains tokens
- [`sanitization-patterns.md`](./sanitization-patterns.md) — sanitization rules block tokens from accidentally landing in publishes
