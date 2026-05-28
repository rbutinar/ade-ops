# /powerbi-model-create — Scaffold a New Power BI Semantic Model (TMDL)

You are creating a **new** Power BI semantic model skeleton as TMDL files under the project. This is a file-only operation — no MCP, no remote.

After scaffolding, open the model in Power BI Desktop to validate syntax and continue authoring, or use `/powerbi-publish` to deploy.

> **DirectLake source?** This skill scaffolds an **Import-mode** model with M
> expressions against a Databricks SQL warehouse. If your source is a Fabric
> Lakehouse and you want DirectLake binding, use `/powerbi-directlake-create`
> instead — it generates the `mode: directLake` partitions and `DatabaseQuery`
> M expression bound to the lakehouse SQL endpoint.

## Prerequisites

- Project `config/project.yaml` with `environments.{env}.platforms.databricks` (used to populate M expressions for Databricks tables)
- A target directory (default: `src/power_bi/{ModelName}.SemanticModel/`)

## Usage

```
/powerbi-model-create {ModelName}                              # bare skeleton
/powerbi-model-create {ModelName} --env {env}                  # populate M expressions from env's Databricks config
/powerbi-model-create {ModelName} --tables fact,dim1,dim2      # also stub these tables
/powerbi-model-create {ModelName} --output {path}              # write under a custom folder
```

## Behavior

### Step 1: Resolve project + paths

Find the active project. Defaults:
- output: `{project_root}/src/power_bi/{ModelName}.SemanticModel/`
- if `--output` is given, use it relative to project root

Refuse to overwrite an existing folder unless the user explicitly confirms.

### Step 2: Read Databricks config (if `--env` given)

```yaml
environments.{env}.platforms.databricks.host
environments.{env}.platforms.databricks.catalog
environments.{env}.platforms.databricks.schema
```

These populate the M template. If `--env` is omitted, leave placeholders.

### Step 3: Create folder structure

```
{output}/
  definition/
    database.tmdl
    model.tmdl
    tables/
      {table_1}.tmdl
      ...
```

### Step 4: Write `database.tmdl`

```tmdl
database {ModelName}
	compatibilityLevel: 1605

	annotation PBI_QueryOrder = ["{table_list_json}"]
```

(Tabs for indentation — TMDL does not accept spaces.)

### Step 5: Write `model.tmdl`

```tmdl
model Model
	culture: en-US
	defaultPowerBIDataSourceVersion: powerBI_V3

	/// Relationships will be added as tables are defined.
```

### Step 6: For each `--tables {name}` (or default minimal set)

Write `definition/tables/{name}.tmdl`:

```tmdl
table {name}
	lineageTag: {name}-001

	/// TODO: Add columns from the source table.
	/// Example:
	/// column column_name
	///     dataType: string
	///     sourceColumn: column_name
	///     summarizeBy: none

	/// TODO: Add measures.
	/// measure 'Measure Name' = DAX_EXPRESSION
	///     formatString: #,##0.00

	partition {name} = m
		mode: import
		source = ```
			let
				Source = Databricks.Catalogs("{host_without_https}", "/sql/1.0/warehouses/{warehouse_id_placeholder}", [Catalog="{catalog}", Database="{schema}"]),
				Table = Source{[Schema="{schema}", Item="{name}"]}[Data]
			in
				Table
			```
```

`{host_without_https}`: take `environments.{env}.platforms.databricks.host`, strip `https://`.
`{warehouse_id_placeholder}`: leave as a placeholder for the user — we don't carry a default warehouse id in `project.yaml` today.

### Step 7: Report

```
=== Power BI Model Create ===
Project:  {project_name}
Env:      {env|--}
Output:   {output_path}

Created:
  ✓ definition/database.tmdl
  ✓ definition/model.tmdl
  ✓ definition/tables/{...}.tmdl  (x N)

Next steps:
1. Edit table definitions to add columns and measures
2. Configure relationships in model.tmdl
3. Fill in the warehouse id in M expressions
4. Open the .SemanticModel folder in Power BI Desktop to validate
5. Use /powerbi-publish --env {env} to deploy to Fabric
```

### Step 8: Log

```
{ISO_timestamp} | {role} | PBI-CREATE | -- | {output_path}: {n} tables stubbed | {ok|fail}
```

## TMDL Syntax Reminders

- **Tabs only** for indentation (not spaces)
- `lineageTag` must be unique across the model
- M expressions use triple-backtick fences in TMDL
- Triple-slash `///` is the comment marker
