"""Build a Power BI semantic model in TMDL with DirectLake binding.

DirectLake is the third storage mode (after Import and DirectQuery) where the
semantic model reads Delta files directly from OneLake without import or query
translation. The TMDL representation has three distinctive markers:

1. An ``expression`` of kind ``m`` that opens a ``Sql.Database`` against the
   Lakehouse's SQL endpoint connection string + endpoint id.
2. Each table partition uses ``mode: directLake`` (lowercase) with
   ``expressionSource`` pointing at that expression.
3. The model's ``defaultPowerBIDataSourceVersion`` is ``powerBI_V3`` (PBIR
   format requirement, also required for DirectLake).

This builder generates the minimum file set that Fabric will accept as a
SemanticModel item. Schema introspection (column types) is left to the
caller — we accept a structured ``TableSpec`` to avoid coupling this builder
to a particular SQL/Spark client. The companion `/migration-assess --execute`
flow can introspect via `FabricLakehouseManager.list_tables` and feed the
result here.

Caveats:
- DirectLake requires the underlying Delta tables to exist in the lakehouse
  before the semantic model is opened. Refreshing a model that points at
  empty/missing tables fails — populate via the pipeline run first.
- This MVP scaffolds the file shape; advanced features (calculation groups,
  RLS, perspectives) are out of scope.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal

# TMDL column data types — minimal mapping from SQL/Spark to Tabular.
TMDL_TYPE_MAP: dict[str, str] = {
    "string": "string",
    "varchar": "string",
    "char": "string",
    "text": "string",
    "int": "int64",
    "integer": "int64",
    "long": "int64",
    "bigint": "int64",
    "smallint": "int64",
    "tinyint": "int64",
    "double": "double",
    "float": "double",
    "real": "double",
    "decimal": "decimal",
    "numeric": "decimal",
    "bool": "boolean",
    "boolean": "boolean",
    "bit": "boolean",
    "date": "dateTime",
    "datetime": "dateTime",
    "timestamp": "dateTime",
    "datetime2": "dateTime",
    "binary": "binary",
}


@dataclass
class ColumnSpec:
    name: str
    sql_type: str  # raw type from source (e.g. "bigint", "string", "boolean")

    @property
    def tmdl_type(self) -> str:
        return TMDL_TYPE_MAP.get(self.sql_type.lower(), "string")


@dataclass
class TableSpec:
    name: str                   # display name (same used in TMDL `table` block)
    source_entity: str          # lakehouse table name (Delta)
    columns: list[ColumnSpec]
    schema_name: str = "dbo"    # the SQL schema in the Lakehouse SQL endpoint


@dataclass
class MeasureSpec:
    name: str
    expression: str             # DAX
    table: str                  # owning table (TMDL requires it)
    format_string: str | None = None
    description: str | None = None


@dataclass
class DirectLakeModelSpec:
    """High-level description of the semantic model to build."""
    database_name: str
    expression_name: str = "DirectLake_DBConnection"
    tables: list[TableSpec] = field(default_factory=list)
    measures: list[MeasureSpec] = field(default_factory=list)
    culture: str = "en-US"
    compatibility_level: int = 1604


# ---------------------------------------------------------------------------
# TMDL fragment builders
# ---------------------------------------------------------------------------

def _lineage_tag() -> str:
    return str(uuid.uuid4())


def build_database_tmdl(spec: DirectLakeModelSpec) -> str:
    return f"""database {spec.database_name}

\tcompatibilityLevel: {spec.compatibility_level}
"""


def build_model_tmdl(spec: DirectLakeModelSpec) -> str:
    return f"""model Model

\tculture: {spec.culture}
\tdefaultPowerBIDataSourceVersion: powerBI_V3
\tsourceQueryCulture: {spec.culture}
\tdataAccessOptions
\t\tlegacyRedirects
\t\treturnErrorValuesAsNull

\tannotation PBI_TimeIntelligenceEnabled = 0

\tannotation PBI_QueryOrder = ["{spec.expression_name}"]
"""


def build_expression_tmdl(spec: DirectLakeModelSpec, sql_endpoint_connection: str, sql_endpoint_id: str) -> str:
    """Build the M expression that opens the Lakehouse SQL endpoint.

    ``sql_endpoint_connection`` is the FQDN returned by
    ``FabricLakehouseManager.get_sql_endpoint()['connection_string']``.
    ``sql_endpoint_id`` is the SQL endpoint item id (used as the database
    name in the M expression).
    """
    return f"""expression {spec.expression_name} =
\t\tlet
\t\t    database = Sql.Database("{sql_endpoint_connection}", "{sql_endpoint_id}")
\t\tin
\t\t    database
\tlineageTag: {_lineage_tag()}
\tkind: m
"""


def _column_tmdl(col: ColumnSpec) -> str:
    return f"""\tcolumn {col.name}
\t\tdataType: {col.tmdl_type}
\t\tsourceColumn: {col.name}
\t\tlineageTag: {_lineage_tag()}
\t\tsummarizeBy: none
"""


def build_table_tmdl(spec: DirectLakeModelSpec, table: TableSpec) -> str:
    columns_block = "\n".join(_column_tmdl(c) for c in table.columns)

    # Measures on this table
    measures = [m for m in spec.measures if m.table == table.name]
    measures_block = ""
    if measures:
        parts = []
        for m in measures:
            fmt = f"\n\t\tformatString: {m.format_string}" if m.format_string else ""
            desc = f"\n\t\t/// {m.description}" if m.description else ""
            parts.append(
                f"\tmeasure '{m.name}' = {m.expression}{fmt}\n"
                f"\t\tlineageTag: {_lineage_tag()}{desc}\n"
            )
        measures_block = "\n" + "\n".join(parts)

    return f"""table {table.name}
\tlineageTag: {_lineage_tag()}

{columns_block}{measures_block}
\tpartition {table.name} = entity
\t\tmode: directLake
\t\tsource
\t\t\tentityName: {table.source_entity}
\t\t\tschemaName: {table.schema_name}
\t\t\texpressionSource: {spec.expression_name}
"""


# ---------------------------------------------------------------------------
# Top-level: assemble the .SemanticModel folder layout
# ---------------------------------------------------------------------------

def build_semantic_model_files(
    spec: DirectLakeModelSpec,
    *,
    sql_endpoint_connection: str,
    sql_endpoint_id: str,
) -> dict[str, str]:
    """Return ``{relative_path: file_content}`` for the SemanticModel folder.

    The shape matches what Fabric ``getDefinition``/``updateDefinition``
    expects when ``format=TMDL``::

        definition/database.tmdl
        definition/model.tmdl
        definition/expressions/{expression_name}.tmdl
        definition/tables/{table_name}.tmdl
        definition.pbism            (model header — minimal version stub)
        .platform                   (Fabric item manifest)

    Callers wrap each file as ``{path, payload (base64), payloadType:InlineBase64}``
    when posting to ``/items`` or ``/updateDefinition`` — the same wrapping
    that ``FabricConnector.group_files`` already does for PBIR.
    """
    files: dict[str, str] = {}

    files["definition/database.tmdl"] = build_database_tmdl(spec)
    files["definition/model.tmdl"] = build_model_tmdl(spec)
    files[f"definition/expressions/{spec.expression_name}.tmdl"] = build_expression_tmdl(
        spec, sql_endpoint_connection, sql_endpoint_id
    )
    for table in spec.tables:
        files[f"definition/tables/{table.name}.tmdl"] = build_table_tmdl(spec, table)

    # Minimal definition.pbism (semantic model item header). PBIR-style:
    files["definition.pbism"] = (
        '{\n'
        '  "version": "4.0",\n'
        '  "settings": {}\n'
        '}\n'
    )

    # Fabric item manifest (.platform). Required for create/update item
    # operations when posting the folder as a definition.
    files[".platform"] = (
        '{\n'
        '  "$schema": "https://developer.microsoft.com/json-schemas/fabric/'
        'gitIntegration/platformProperties/2.0.0/schema.json",\n'
        '  "metadata": {\n'
        f'    "type": "SemanticModel",\n'
        f'    "displayName": "{spec.database_name}"\n'
        '  },\n'
        '  "config": {\n'
        '    "version": "2.0",\n'
        '    "logicalId": "' + _lineage_tag() + '"\n'
        '  }\n'
        '}\n'
    )

    return files


# ---------------------------------------------------------------------------
# Convenience: build from a Lakehouse table inventory
# ---------------------------------------------------------------------------

def build_from_lakehouse_tables(
    *,
    database_name: str,
    lakehouse_tables: list[dict],
    sql_endpoint_connection: str,
    sql_endpoint_id: str,
    measures: list[MeasureSpec] | None = None,
) -> dict[str, str]:
    """Build a DirectLake semantic model from the Lakehouse table inventory.

    ``lakehouse_tables`` is the output of
    ``FabricLakehouseManager.list_tables(lakehouse_id)`` — each entry has at
    minimum a ``name`` field, and the columns are introspected by extending
    this caller (the ``/tables`` endpoint returns names but not full schema;
    the columns can be filled in by a separate SQL endpoint query — out of
    scope for this MVP, but the data structure is ready).

    For the MVP path the caller passes ``TableSpec`` objects directly via
    ``build_semantic_model_files``; this convenience function is the future
    auto-introspection seam.
    """
    tables: list[TableSpec] = []
    for t in lakehouse_tables:
        name = t.get("name") or t["displayName"]
        cols_raw = t.get("columns") or []
        cols = [ColumnSpec(name=c["name"], sql_type=c.get("type", "string")) for c in cols_raw]
        tables.append(TableSpec(name=name, source_entity=name, columns=cols))

    spec = DirectLakeModelSpec(
        database_name=database_name,
        tables=tables,
        measures=measures or [],
    )
    return build_semantic_model_files(
        spec,
        sql_endpoint_connection=sql_endpoint_connection,
        sql_endpoint_id=sql_endpoint_id,
    )
