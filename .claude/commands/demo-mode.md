# /demo-mode — Public-recording safety overrides

You are now in **demo mode** for public-facing demonstrations, screen
recording, or live presentation. This skill overrides default conventions
for the duration of the session.

This is the ade-ops counterpart of the ADE workshop's `demo-mode.md`,
adapted to the ade-ops architecture (Databricks Community Edition +
multi-env Fabric trial tenant under `distributions/demo-claude/`).

## Language override

**Speak English only** for the entire session. This overrides the Italian
conversation rule in the root `CLAUDE.md`. Switch back via plain conversation
or end the session.

## Active environment

- **Project**: `distributions/demo-claude/projects/databricks-fabric-migration`
- **Default env**: `dev` (reuses existing Acme medallion notebooks on DBR CE)
- **Promotion targets**: `cert` and `prod` Fabric workspaces (empty until first push)

### Identities

- **Databricks**: PAT for the demo CE workspace (single-user). The CE user identity is resolved from the `DEMO_USER_EMAIL` env var (used in `project.yaml` and `overlays/dev.yaml` to build the `/Users/{email}/ade_demo/` path).
- **Fabric / Azure AD**: a dedicated demo identity on the demo tenant, signed in via `az login --tenant {tenant} --allow-no-subscriptions`. Tenant + identity configured in `config/project.yaml` and `config/credentials.yaml`.

### Prereqs (env vars)

| Var | Purpose | Example |
|---|---|---|
| `DATABRICKS_TOKEN` | PAT for the CE workspace | `dapi…` |
| `DEMO_USER_EMAIL` | CE user identity (resolves `/Users/{email}/` path) | `you@example.com` |
| `AZURE_TENANT_ID` | Demo Fabric tenant (also read from `project.yaml`) | UUID |

Set them in the parent shell before launching Claude Code (`setx` on Windows or `export` on macOS/Linux).

### Fabric workspaces (already provisioned)

The operator's `credentials.yaml` (or environment variables) supplies the
demo-tenant workspace IDs and capacity ID. Demo placeholders:

| Env | Workspace | Item id |
|---|---|---|
| DEV | `ADE_Demo_Acme_DEV` | `<dev-workspace-id>` |
| CERT | `ADE_Demo_Acme_CERT` | `<cert-workspace-id>` |
| PROD | `ADE_Demo_Acme_PROD` | `<prod-workspace-id>` |

All assigned to capacity `<demo-capacity-id>` (trial SKU).

## Recording safety rules

1. **NEVER** display or reference real client data, real client names, or real client schemas. Use only synthetic Acme Manufacturing terms.
2. **NEVER** show credentials, tokens, connection strings, tenant GUIDs, or workspace UUIDs in terminal output. Substitute with placeholders (`<workspace-id>`, `<tenant>`, `<token>`) before screen capture.
3. If asked about real client engagements the operator works on elsewhere, deflect to demo context — those are private workshop projects, not part of this public demo.
4. Keep terminal output readable — no walls of debug text on screen.
5. Confirm actions before execution; the audience needs to follow.

## Behavior

- Be natural and conversational — this is a real working session, not a script reading.
- When executing skills (`/migration-assess`, `/ops-push`, `/ops-pull`), proceed normally — the demo IS the real workflow.
- Prefer the `governed` mode of `/migration-assess` (default, with confirmations) over `--auto-approve` for live demos with technical audience; reverse the choice for "big-bang operator-like" demos with IT manager audience.

## Confirmation message

When this skill is invoked, confirm activation with:

> **Demo mode active. English-only output. Acme Manufacturing environment loaded. Ready to demonstrate `/migration-assess`.**

ARGUMENTS: $ARGUMENTS
