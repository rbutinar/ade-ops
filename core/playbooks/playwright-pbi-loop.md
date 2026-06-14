# Playwright Power BI visual-feedback loop

A development pattern for programmatic Power BI report work: instead of
operator-driven iteration ("change → deploy → operator screenshots →
diagnose → repeat", ~3–5 min per turn), Claude self-iterates against
the rendered report in seconds.

Discovered 2026-05-23 during the `databricks-fabric-migration` demo.
Single highest-value finding of that session. Cross-distribution:
applicable to any project that touches Power BI.

## The loop

```
build (.py or JSON patch)
    ↓
deploy via REST                  POST /workspaces/{ws}/items/{id}/updateDefinition
    ↓                            (or createItem for new reports)
playwright navigate              mcp__playwright__browser_navigate(report_url)
    ↓                            + mcp__playwright__browser_wait_for(textGone="Loading your report")
snapshot                         mcp__playwright__browser_snapshot       (accessibility tree)
    ↓                            + mcp__playwright__browser_take_screenshot (pixels)
diagnose                         compare to spec; hypothesise root cause
    ↓                            (theme override? transparency? wrong field path?)
empirical probe                  change ONE variable to a high-contrast value
    ↓                            (e.g. ACCENT = "#FF0000") to isolate signal from noise
patch                            back to build step
    ↓
re-deploy + snapshot             loop until spec matches
```

The key insight: Claude can take its own screenshot via the Playwright
MCP. Operator no longer in the inner loop.

## Three operational modes

The loop generalises beyond pure editing into three use cases. A skill
that wraps the loop should expose them as explicit modes:

| Mode | When | Typical env | Read/Write | Notes |
|---|---|---|---|---|
| **edit-iterate** | "Change colour, layout, add a KPI to an existing report" | DEV (or experiment workspace) | Read + Write | Interactive loop. Each turn = JSON patch + push + snapshot + diagnose. |
| **visual-verify** | "User reports card X doesn't render in CERT/PROD — confirm or refute" | switchable (`--env cert` or `--env prod`) | Read-only | One-shot navigate + snapshot. No deploy. |
| **legacy-recon** | "This legacy Wave 1/2 report returns nude 404 from REST but renders in the browser — capture what's there" | CERT/PROD | Read-only | Navigate + snapshot. Same shape as visual-verify but the implicit goal is migration intake, not bug triage. |

Default mode is `edit-iterate` (the value driver). The two read-only
modes share most of the implementation — they're effectively
`edit-iterate` minus the patch+push step.

## Playwright MCP setup

### Prerequisite: Node.js LTS

`@playwright/mcp` is an `npx`-launched server, which requires Node.js on the
operator's machine. On a fresh enterprise workstation without prior frontend
tooling, Node.js is NOT present by default. Failure mode: the MCP server
fails silently at Claude Code startup — no `mcp__playwright__*` tools appear
in the deferred tool list, and there is no clear diagnostic unless the
operator thinks to run `npx --version`.

Verify both must respond:

```
node --version
npx --version
```

If missing, install:

- **Windows**: `winget install OpenJS.NodeJS.LTS` (~30s, v24.x LTS as of 2026-05)
- **macOS**: `brew install node`
- **Linux**: distribution-appropriate (`apt`, `dnf`, or `nvm`)

After install, **restart Claude Code** so the updated `PATH` is inherited by
MCP server subprocesses (otherwise the playwright block stays dark even
though `npx` works in a fresh terminal).

Documented by an operator finding F-G2 and a parallel ops-local-manager
finding 2026-05-25 — two independent reports within hours of each other
on the same fresh-clone path.

### Project-level `.mcp.json` entry

Per-project `.mcp.json` overrides user-level. Two template flavours — **Strategy A is the recommended default**. Strategy B is documented for existing seats that haven't migrated yet.

> **Quick choice**: new seat or fresh setup → Strategy A. Existing seat already running Strategy B and working acceptably → keep Strategy B but plan a migration window. Strategy A eliminates the "close all Edge windows before each invocation" friction that Strategy B requires.

**Strategy A — dedicated profile (RECOMMENDED — eliminates Edge-kill friction)**:

```json
"playwright": {
  "type": "stdio",
  "command": "npx",
  "args": [
    "-y",
    "@playwright/mcp@0.0.37",
    "--browser", "msedge",
    "--user-data-dir", "C:/Users/<your-user>/.playwright_edge_<seat>"
  ],
  "env": {}
}
```

**Strategy B — shared user-data-dir with `--profile-directory` (LEGACY — requires Edge-kill before each invocation)**:

> **Caveat**: this strategy was the original pattern before Strategy A was validated (ade-ops-2 dogfooding 2026-05-28: 3 sequential navigates with zero Edge-kill needed using dedicated `--user-data-dir`). The shared-profile approach reuses existing SSO cookies but requires closing ALL Edge windows before each Playwright invocation (Chromium single-instance per userDataDir). Operationally heavier; migrate to Strategy A on the next setup cycle.

`@playwright/mcp@0.0.37` does NOT expose `--profile-directory` as a top-level CLI flag (verified empirically 2026-05-24, finding F3). Use `--config <path>` pointing at a JSON config file:

```json
"playwright": {
  "type": "stdio",
  "command": "npx",
  "args": ["-y", "@playwright/mcp@0.0.37",
           "--config", "distributions/<dist>/projects/<proj>/local/playwright-mcp-config.json"],
  "env": {}
}
```

with `local/playwright-mcp-config.json` (gitignored, per-seat):

```json
{
  "browser": {
    "browserName": "chromium",
    "userDataDir": "C:/Users/<your-user>/AppData/Local/Microsoft/Edge/User Data",
    "launchOptions": {
      "channel": "msedge",
      "args": ["--profile-directory=Profile <N>"]
    }
  }
}
```

**Critical on `browserName`** (finding F-G1, 2026-05-25): Playwright's JS API only accepts `chromium` / `firefox` / `webkit` as top-level `browserName`. Microsoft Edge is reached via `chromium` + `launchOptions.channel: "msedge"`. Using `"browserName": "msedge"` directly raises `TypeError: Cannot read properties of undefined (reading 'launchPersistentContext')` because `playwright.msedge` is undefined. The CLI flag `--browser msedge` of `@playwright/mcp` (used by Strategy A above) is different and remains valid — it is the CLI shorthand that internally maps to `chromium`+`channel: msedge`.

Find the right `Profile <N>` by inspecting `User Data/Profile <N>/Preferences` (JSON) and matching `account_info[].email` against the SSO identity you want (e.g. `*@<your-domain>` for guest-on-client-tenant). Real-world enterprise workstations carry 20+ Profile folders and **no** `Default` profile (finding F3).

### MCP scope priority (user vs project)

Claude Code resolves MCP servers across two scopes: **user** (`~/.claude.json` `mcp` key, applies everywhere) and **project** (`<repo>/.mcp.json`, applies only when working in that repo). When the same server name appears in both, **project wins**.

This is the intended mechanism for multi-distribution Playwright setups. Typical layout when one operator works across several distributions:

| Scope | Endpoint example | Active when |
|---|---|---|
| user | `--user-data-dir .../.playwright_edge_<default-distro>` | Working dir without a project-level override (e.g. consumer clones of the default distribution) |
| project | `--user-data-dir .../.playwright_edge_<this-distro>` | Working dir is under this repo (project-level override) |

**Who hits this warning**: only operators who configure **both** scopes. A team member working on a single distribution typically configures only the project scope (via `cp .mcp.example.json .mcp.json` during onboarding) and never sees the `/mcp` conflicting-scopes warning. The framework manager, who alternates between the lab and consumer clones of the same operator workstation, deliberately keeps both scopes to get per-working-dir override behaviour.

Concrete example on this lab: user scope points at the default-distribution profile for use across consumer clones that do not ship their own playwright `.mcp.json`; project scope on the lab repo points at a distinct distribution-specific profile so cross-distribution work from the lab picks up the right tenant identity, not the default one.

Running `/mcp` emits a `[Conflicting scopes]` warning whenever the two endpoints differ. **This is cosmetic and expected** — OAuth tokens are stored per-endpoint (no cross-distribution token leakage), and "project wins" gives exactly the desired per-working-dir override. Three options:

1. **Ignore the warning** (recommended) — it confirms the multi-profile setup is active and each working dir resolves to its correct profile.
2. **Remove one scope** (`claude mcp remove playwright -s user` or `-s project`) — collapses to a single profile. Use only if a single distribution is enough; loses per-working-dir override.
3. **Align the two endpoints** — make user and project point at the same profile. Same effect as (2), keeps both entries cosmetically.

### Edge profile strategy

Two options, pick per distribution:

**A. Dedicated Playwright profile** (`--user-data-dir` points at a fresh
folder): isolates the Playwright session from the operator's normal
browsing. **Caveat**: even with `--user-data-dir`, Edge may still
surface Windows-SSO-linked accounts in the auth picker (observed 2026-05-23
on the demo seat). Full identity isolation requires a different approach
(e.g. Chromium-vanilla + manual login each time).

**B. Default Edge profile of the operator** (`--user-data-dir` points at
the standard user profile): less isolation, but no auth friction — the
operator's Windows-SSO identity is already valid for the target tenant.

For guest-on-client-tenant setups, **option B is the recommended default**:
the operator already has the guest identity authenticated against the
client tenant via Windows-SSO. Avoiding a dedicated profile means no
second login.

For demo/playground distributions, **option A** is used (`--user-data-dir`
to a dedicated folder), because the demo seat may run on a machine where
the default Edge profile is logged into a different tenant.

### Critical prereq for Strategy B (multi-profile workstations)

Chromium enforces **single-instance per `userDataDir`**. If the operator
has Edge already running on the same user-data-dir, Playwright's
spawned window merges into the existing Edge process and loses control:
errors like `No frame with given id found` / `Execution context was
destroyed` (finding F6, 2026-05-24).

**Prereq before invoking any Playwright skill on Strategy B**: close
ALL Edge windows, including child processes (Task Manager). After the
session, `Ctrl+Shift+T` restores tabs.

This caveat does NOT apply to Strategy A (dedicated `--user-data-dir`
that the operator never opens manually).

### Deep-link URL composition for guest identities

Standard PBI service URL `https://app.powerbi.com/groups/{ws}/reports/{id}/ReportSection`
is **incomplete for guest identities** (vendor-on-client tenant setups).
Without `?ctid={tenant_id}`, the user authenticates in their home tenant
where the report doesn't exist → misleading dialog *"Sorry, we couldn't
find that report..."* that looks like a permission issue but is a URL
defect (finding F7, quadruple repro 2026-05-24).

Always use:

```
https://app.powerbi.com/groups/{ws}/reports/{id}/ReportSection?ctid={tenant_id}&experience=power-bi
```

Read `{tenant_id}` from the overlay:
`environments.{env}.platforms.fabric.auth.az_tenant_id`. Configure it
in your distribution's overlay; never hardcode tenant UUIDs in shared docs.

### Runtime artifacts

Playwright MCP creates a `.playwright-mcp/` directory in the cwd at first
run (session cache, browser state). This directory is **gitignored**
project-wide via the root `.gitignore` MCP runtime config section. Do
not commit it.

### Snapshot cadence and ref invalidation

`mcp__playwright__browser_snapshot` has an internal default ~5s timeout.
On PBI cold-start (Loading your report → first render), the page exceeds
that and `browser_snapshot` retries 3+ times with chat noise. Two
mitigations:

- **Wait first**: explicit `browser_wait_for(time=3)` before `browser_snapshot`
  on the first call after navigation. Reduces retries.
- **`browser_wait_for(textGone=...)`**: when waiting for a specific UI
  signal (e.g. "Loading your report" gone), this is the preferred
  pattern over a fixed `time` value.

A separate issue (finding F9): `browser_click` requires a fresh
`ref` from the most recent snapshot. After any DOM mutation (tab change
in PBI, expanding a slicer), all `ref`s rotate, forcing a snapshot
between every click. On PBI pages with ~700 a11y-tree nodes this
explodes chat output.

**Canonical workaround — `browser_evaluate` for known-list clickables**:

```javascript
// Click a tab by text content without needing a snapshot
Array.from(document.querySelectorAll('[role="tab"]'))
  .find(t => t.textContent.includes('Coverage Dashboard'))
  ?.click();
```

Pattern works for tabs, slicer values, button rows — any clickable that
can be identified by a stable text or attribute. Use `browser_evaluate`
once after navigation, then iterate clicks without re-snapshotting.
Reserve `browser_snapshot` + `browser_click(ref=…)` for the cases where
the element is identifiable only by its `ref` (rare for PBI workloads).

## Empirical findings catalogue

The loop is the discovery mechanism. The findings it produced live in
`pbir_gotchas.md` as a maintained list — six silent-failure modes so far
(container-level styling slot, transparency `0D` required, theme JSON
audit gap, etc.). Read that document before starting a build session —
it saves the discovery cost.

## Implementation notes for a PBI loop skill

A future skill that wraps this loop should:

1. **Accept a report reference** (path under `state/{env}/power_bi/Report/`
   or a Fabric report ID) and a mode (`edit` / `verify` / `recon`).
2. **Resolve the target workspace and report URL** from the env overlay
   (`report_workspace_id` for the env) and the report's `.platform`
   logicalId or Fabric item id lookup.
3. **Open Playwright** with the configured Edge profile (option A or B
   per distribution).
4. **For edit mode**: pull report parts if not already in `state/`, enter
   the prompt-loop (user describes change → patch → push → screenshot
   → diagnose → continue / approve / abort).
5. **For verify / recon**: navigate + screenshot + return — no
   modifications.
6. **Log each iteration** so a session can be replayed or audited.
7. **Respect distribution-level safety**: edit mode default env is
   `dev`, push to `cert` / `prod` requires explicit `--env` + confirmation
   (or a double-confirm token for prod, mirroring the
   `/ddf-operator` pattern for production writes).

## See also

- `pbir_gotchas.md` — silent-failure modes the loop is designed to surface
- `docs/feedback/2026-05-23_pbir-report-build-needs-wrapper-helpers.md`
  — broader architectural proposal that includes this loop as one
  component alongside the `pbir_engine` port and theme presets
