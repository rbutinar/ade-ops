# /powerbi-model-edit — Live Edit a Power BI Model via MCP

You are editing a **running** Power BI Desktop model via the `powerbi` MCP server. Operations are interactive: measures, tables, DAX validation, TMDL export.

This skill is local-only — it does not touch Fabric. To publish to the service after editing, use `/powerbi-publish`.

## Prerequisites

- Power BI Desktop running with a model open (.pbix or .SemanticModel)
- `powerbi` MCP server configured in `.mcp.json` (see ONBOARDING.md Step 7)
- Model must be fully loaded (not refreshing)

## Usage

```
/powerbi-model-edit                                       # connect, show inventory
/powerbi-model-edit measures                              # list all measures
/powerbi-model-edit add-measure {table} {name} {dax}      # add a measure
/powerbi-model-edit tables                                # list tables
/powerbi-model-edit validate "{dax_expression}"           # validate DAX
/powerbi-model-edit export {output_dir}                   # export model to TMDL folder
```

## Behavior

### Step 1: Discover instances

```
mcp__powerbi__connection_operations(operation="ListLocalInstances")
```

If multiple: ask the user. If none: instruct to open the model in PBI Desktop.

### Step 2: Connect

```
mcp__powerbi__connection_operations(operation="Connect", dataSource="localhost:{port}")
```

### Step 3: Execute operation

#### `measures` — List

```
mcp__powerbi__measure_operations(operation="List")
```

Render: name, table, format string, expression preview.

#### `add-measure {table} {name} {dax}`

Validate first:

```
mcp__powerbi__dax_query_operations(
  operation="Validate",
  query="EVALUATE {{ {dax} }}"
)
```

If valid, create:

```
mcp__powerbi__measure_operations(
  operation="Create",
  definitions=[{
    tableName: "{table}",
    name: "{name}",
    expression: "{dax}",
    formatString: "#,##0.00"
  }]
)
```

Remind the user: **changes only persist if they save in Power BI Desktop**.

#### `tables` — List

```
mcp__powerbi__table_operations(operation="List")
```

#### `validate "{dax}"`

```
mcp__powerbi__dax_query_operations(operation="Validate", query="EVALUATE {dax}")
```

Show errors with line/column info if any.

#### `export {output_dir}`

```
mcp__powerbi__database_operations(
  operation="ExportToTmdlFolder",
  tmdlFolderPath="{output_dir}/{ModelName}.SemanticModel"
)
```

Use this regularly for version control — TMDL is text-friendly under git.

## MCP Operations Reference

| MCP tool | Use case |
|---|---|
| `connection_operations` | Connect / disconnect |
| `table_operations.List/Get` | Inventory / detail |
| `measure_operations.Create/Update/Delete/Move` | DAX measures |
| `dax_query_operations.Execute/Validate` | Test / validate DAX |
| `database_operations.ExportToTmdlFolder` | Backup / version control |

## When to Use This vs `/powerbi-model-create`

| Use this | Use `/powerbi-model-create` |
|---|---|
| Model is open in PBI Desktop | Bootstrapping a new model from scratch |
| Adding/modifying measures incrementally | Generating TMDL skeleton (offline) |
| Quick DAX validation | Batch table creation |
| Immediate UI feedback | Structural changes via files |

## Logging

Read-only operations (`measures`, `tables`, `validate`, `export`) are **not logged** to `ops.log`.

Write operations (`add-measure`, future edit/delete):

```
{ISO_timestamp} | {role} | PBI-EDIT | local | {operation}: {detail} | {ok|fail}
```

## Troubleshooting

- **No instances found** → open the model in PBI Desktop, wait for full load
- **Connection timeout** → restart PBI Desktop, ensure MCP server is running
- **Repeated MCP failures** → `connection_operations(operation="Disconnect")`, restart PBI Desktop, reconnect

## Notes

- Changes via MCP require a manual save in Power BI Desktop to persist on disk.
- Export to TMDL regularly so your changes survive in git.
- For complex DAX, run `Execute` (not just `Validate`) to confirm result.

## Visual verification of bound reports

DAX edits via MCP only mutate the local PBI Desktop session. Once persisted on disk (manual save) and published via `/powerbi-publish`, downstream reports that bind to this model may behave differently — a renamed measure breaks visuals that reference it by name, a changed format string changes display formatting, a relationship edit can change row counts.

After publishing the edited model, use the Playwright visual-feedback loop to verify at least one consuming report still renders correctly:

- **For <client> reports**: `/<client>-pbi-loop verify {report-ref} --env {env}`
- **For other distributions**: see `core/playbooks/playwright-pbi-loop.md` for the general pattern

This is especially important for: measure renames, removed measures, format-string changes, relationship modifications. Pure additive measure work (new measure, no existing visual touched) is lower risk.
