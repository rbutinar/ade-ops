---
status: preview
since: 2026-05-23
related: powerbi-publish, powerbi-model-create, pbir-create, <client>-pbi-loop
---

# /powerbi-directlake-create — Scaffold a New DirectLake Semantic Model (TMDL) (preview)

You are creating a **new** Power BI semantic model bound to a Microsoft Fabric
Lakehouse via **DirectLake** mode. This is a file-only operation — no MCP, no
remote publish (use `/powerbi-publish` after authoring).

Use this skill when the source is a Fabric Lakehouse. For Databricks-backed
**Import-mode** models, use `/powerbi-model-create` instead.

## Prerequisites

- Project `config/project.yaml` with `environments.{env}.platforms.fabric` —
  `workspace_id` and `lakehouse_name` populated
- Active Azure CLI session on the right tenant (`az_cli` auth method) OR a
  service principal in `credentials.yaml.fabric`
- The target Lakehouse exists and contains the tables you want to model. If
  the tables are empty (no Delta files yet), the model publishes but visuals
  show no data.
- A **tables manifest** YAML listing the lakehouse tables + columns you want
  in the model. Auto-discovery from the SQL endpoint is on the roadmap (see
  `docs/backlog/`) but not in v1.

## Usage

```
/powerbi-directlake-create {ModelName} --manifest path/to/tables.yaml --env dev
/powerbi-directlake-create {ModelName} --manifest tables.yaml --env dev --output custom/path
/powerbi-directlake-create {ModelName} --manifest tables.yaml --env dev --measures measures.yaml
```

## Manifest format

`tables.yaml` (one per model):

```yaml
tables:
  - name: fct_sales              # name in the semantic model
    source_entity: gold_ft_sales # name in the lakehouse (mapped to entityName)
    schema_name: dbo             # SQL schema in the lakehouse SQL endpoint (default: dbo)
    columns:
      - { name: sale_date,       type: string,  summarize_by: none }
      - { name: product_id,      type: string,  summarize_by: none }
      - { name: total_revenue,   type: double,  summarize_by: sum  }
      - { name: total_quantity,  type: int64,   summarize_by: sum  }

  - name: dim_product
    source_entity: gold_dm_product
    columns:
      - { name: product_id,   type: string }
      - { name: product_name, type: string }
      - { name: category,     type: string }

relationships:
  - from: fct_sales.product_id
    to:   dim_product.product_id
```

`measures.yaml` (optional):

```yaml
measures:
  - name: Total Revenue
    table: fct_sales
    expression: SUM(fct_sales[total_revenue])
    format_string: '"$"#,0.00;-"$"#,0.00;"$"#,0.00'

  - name: Distinct Products Sold
    table: fct_sales
    expression: DISTINCTCOUNT(fct_sales[product_id])
    format_string: '#,0'
```

## Behavior

### Step 1: Resolve project + paths

Find the active project (`config/project.yaml` walking up from cwd). Defaults:
- Output: `{project_root}/src/power_bi/{ModelName}.SemanticModel/`
- If `--output` is given, use it relative to project root.

Refuse to overwrite an existing folder unless the user explicitly confirms.

### Step 2: Resolve Fabric env config

```yaml
environments.{env}.platforms.fabric.workspace_id     # required
environments.{env}.platforms.fabric.lakehouse_name   # required
```

Load credentials from `config/credentials.yaml` (gitignored) for the `fabric`
section. Construct a `FabricAuthenticator` + `FabricClient`.

### Step 3: Discover lakehouse + SQL endpoint

```python
from core.platforms.fabric.lakehouse_manager import FabricLakehouseManager

lh_mgr = FabricLakehouseManager(client, workspace_id)
lh = lh_mgr.find_lakehouse(lakehouse_name)         # by display name
sql_ep = lh_mgr.get_sql_endpoint(lh["id"])         # poll until Ready
```

Hard error if `find_lakehouse` returns None — instruct the user to run
`/migration-assess --execute` first or create the lakehouse manually.

Hard error if the SQL endpoint connection string is still null after the poll
(typical when the lakehouse is brand new and provisioning hasn't completed) —
instruct the user to wait a minute and retry.

### Step 4: Parse manifest

Load `--manifest` (and optional `--measures`) YAML. Convert to the dataclass
specs the builder consumes:

```python
from core.parsers.tmdl_directlake_builder import (
    ColumnSpec, TableSpec, MeasureSpec, DirectLakeModelSpec,
    build_semantic_model_files,
)

tables = [
    TableSpec(
        name=t["name"],
        source_entity=t["source_entity"],
        schema_name=t.get("schema_name", "dbo"),
        columns=[ColumnSpec(name=c["name"], sql_type=c["type"]) for c in t["columns"]],
    )
    for t in manifest["tables"]
]
measures = [MeasureSpec(**m) for m in (measures_manifest or {}).get("measures", [])]

spec = DirectLakeModelSpec(
    database_name=lakehouse_name,
    tables=tables,
    measures=measures,
)
```

### Step 5: Build TMDL files

```python
files = build_semantic_model_files(
    spec,
    sql_endpoint_connection=sql_ep["connection_string"],
    sql_endpoint_id=sql_ep["id"],
)
```

The builder returns a `dict[str, str]` keyed by relative file path
(e.g. `definition/tables/fct_sales.tmdl`). Write each entry under the output
folder, creating intermediate directories as needed.

### Step 6: Write relationships (if present in manifest)

Append `definition/relationships.tmdl`:

```tmdl
relationship rel_{from_table}_{to_table}
	fromColumn: {from_table}.{from_column}
	toColumn:   {to_table}.{to_column}
```

One block per `relationships:` entry in the manifest. The builder does not
synthesize relationships today — they live in the manifest as user intent.

### Step 7: Report

```
=== Power BI DirectLake Model Create ===
Project:        {project_name}
Env:            {env}
Lakehouse:      {lakehouse_name} ({lakehouse_id})
SQL endpoint:   {connection_string}
Output:         {output_path}

Created:
  ✓ definition.pbism
  ✓ definition/database.tmdl
  ✓ definition/model.tmdl
  ✓ definition/expressions.tmdl
  ✓ definition/tables/{...}.tmdl  (x N)
  ✓ definition/relationships.tmdl  (if relationships in manifest)

Next steps:
1. Review the generated TMDL — measure DAX is just stubbed, validate against your model
2. Open the .SemanticModel folder in Power BI Desktop (or Fabric portal) to validate syntax
3. Use /powerbi-publish --env {env} to deploy to the Fabric workspace
4. Build a PBIR report on top via /pbir-report or the Fabric portal
5. After publishing the bound report, verify visually via the Playwright loop
   (see core/playbooks/playwright-pbi-loop.md) or, for <client> reports,
   /<client>-pbi-loop verify {report-ref} --env {env}
```

### Step 8: Log

Append to `docs/ops.log` (framework level) AND the project `ops.log`:

```
{ISO_timestamp} | {role} | PBI-DL-CREATE | {env} | {output_path}: {n} tables, {m} measures, {r} relationships | {ok|fail}
```

`{role}` is the persona slug **actually active** (`ddf-operator`, `ops-dev`,
`ops-manager`, ...), or `claude-adhoc` if operating without a persona — never a
persona slug you are not operating as (see [`core/conventions/ops-log.md`](../../core/conventions/ops-log.md)).

## Safety

- **File-only** — this skill never POSTs to Fabric. Publishing is
  `/powerbi-publish`, which has its own confirmation gate.
- **No credentials leak** — the SQL endpoint connection string is written
  into the TMDL `expressions` file (it's a hostname, not a secret), but the
  Fabric token is never serialized anywhere on disk.
- **No state mutation** — even if `--env cert` or `--env prod` are passed,
  no remote write happens. Env is only used to resolve the lakehouse target
  for TMDL binding metadata.

## TMDL Syntax Reminders

- **Tabs only** for indentation (TMDL does not accept spaces)
- `lineageTag` must be unique across the model — the builder generates UUIDs
- DirectLake partitions look like:
  ```tmdl
  partition {table} = entity
  	mode: directLake
  	source
  		entityName: {lakehouse_table}
  		schemaName: dbo
  		expressionSource: DatabaseQuery
  ```
- The `DatabaseQuery` M expression binds the model to the lakehouse SQL endpoint:
  ```tmdl
  expression DatabaseQuery =
  		let
  			database = Sql.Database("<sql_endpoint_host>", "<lakehouse_name>")
  		in
  			database
  ```

## Related skills

- `/powerbi-model-create` — Import-mode sibling for Databricks SQL warehouses
- `/powerbi-publish` — deploy the resulting `.SemanticModel/` folder to Fabric
- `/pbir-report` — build a PBIR report on top of the published model
- `/migration-assess --execute` — provisions the lakehouse + populates tables
  upstream of this skill
- the iterative PBI loop skill — visual-feedback loop on existing <client> reports (verify post-deploy
  rendering against the new DirectLake model). For non-<client> distributions, the loop
  pattern itself is documented in `core/playbooks/playwright-pbi-loop.md`
