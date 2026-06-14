"""Databricks platform integrations — REST clients, ingestion helpers."""

from .sql_ingest_via_rest import (
    DatabricksSqlIngestError,
    pull_table_via_rest,
    map_databricks_type_to_spark,
)

__all__ = [
    "DatabricksSqlIngestError",
    "pull_table_via_rest",
    "map_databricks_type_to_spark",
]
