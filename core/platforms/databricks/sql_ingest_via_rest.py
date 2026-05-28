"""Databricks SQL ingestion via REST API — JDBC-free cross-cloud reader.

Wraps the Databricks SQL Statement Execution REST API
(``POST /api/2.0/sql/statements``) for one-shot table reads. Designed for
environments where the JDBC driver is not available or `%pip install` is
disabled (e.g. Microsoft Fabric Spark notebook on Trial capacity, as
documented in the release-readiness assessment P2-D of 2026-05-27).

Why exists:
  - Fabric Mirrored Databricks Catalog only supports **Azure** Databricks
    (host pattern ``adb-*.azuredatabricks.net``).
  - For AWS / free-tier / GCP Databricks sources, Mirroring is not
    available — operators must either install JDBC + secret transfer,
    or use this REST helper that ships only stdlib (urllib + json).
  - The Statement Execution API returns rows in chunks of JSON arrays;
    pagination + reassembly is non-trivial enough to deserve a helper.

What it does NOT do:
  - Streaming infinite-row reads (loads the full result into memory).
  - Authentication beyond a PAT (no OAuth / managed identity yet).
  - Bulk-load to Delta — that is the caller's responsibility (typically
    a Fabric notebook ``spark.createDataFrame(...).write...saveAsTable``).

Closes P2-D + P3-B from the ade-ops-2 release-readiness assessment.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterator


# Polling defaults — Statement Execution is async on long-running queries.
_POLL_INTERVAL_SECONDS = 2.0
_POLL_MAX_SECONDS = 600.0


class DatabricksSqlIngestError(RuntimeError):
    """Raised on unrecoverable error during REST ingest."""


def map_databricks_type_to_spark(databricks_type: str) -> str:
    """Map a Databricks schema type to the Spark equivalent.

    Closes P3-B: when fetching with ``format=JSON_ARRAY`` the values come
    back as strings regardless of the column declared type. Building a
    typed Spark DataFrame requires either custom casting per type or this
    canonical mapping.

    Args:
        databricks_type: As returned by the Statement Execution API
            ``schema.columns[i].type_text``. May include precision
            qualifiers (e.g. ``DECIMAL(38,10)``, ``TIMESTAMP``).

    Returns:
        The Spark type literal as accepted by
        ``pyspark.sql.types._parse_datatype_string``. Falls back to
        ``string`` for unmapped types — caller may need to handle those.
    """
    t = (databricks_type or "string").strip().upper()
    # Stripping parametric qualifiers for the dispatch:
    base = t.split("(", 1)[0].strip()
    mapping = {
        "STRING": "string",
        "VARCHAR": "string",
        "CHAR": "string",
        "BOOLEAN": "boolean",
        "TINYINT": "byte",
        "BYTE": "byte",
        "SMALLINT": "short",
        "SHORT": "short",
        "INT": "integer",
        "INTEGER": "integer",
        "BIGINT": "long",
        "LONG": "long",
        "FLOAT": "float",
        "REAL": "float",
        "DOUBLE": "double",
        "DATE": "date",
        "TIMESTAMP": "timestamp",
        "TIMESTAMP_NTZ": "timestamp",
        "BINARY": "binary",
    }
    if base in mapping:
        return mapping[base]
    if base == "DECIMAL" or base == "NUMERIC":
        # Preserve precision / scale when present.
        if "(" in t:
            return f"decimal{t[t.index('('):]}".lower()
        return "decimal(38,10)"
    # Complex types we do not auto-map (ARRAY, MAP, STRUCT). Caller may
    # need a custom parser; fall through to string.
    return "string"


def pull_table_via_rest(
    *,
    host: str,
    warehouse_id: str,
    token: str,
    source_table: str,
    row_limit: int | None = None,
    timeout: float = _POLL_MAX_SECONDS,
) -> Iterator[dict[str, Any]]:
    """Fetch a table from Databricks via the SQL Statement Execution REST API.

    One-shot, in-memory. Pages through ``/result/chunks/{idx}`` internally
    so callers receive a single flat iterator of dict rows.

    Args:
        host: Databricks workspace URL, with or without scheme. The
            function normalises to ``https://<host>``.
        warehouse_id: SQL Warehouse id (NOT the cluster id). The warehouse
            must be in ``RUNNING`` or ``STARTING`` state; if ``STOPPED``,
            the statement will start it (cold-start ~30-60s).
        token: Databricks PAT with at least ``CAN_USE`` on the warehouse.
        source_table: Fully-qualified table name (``catalog.schema.table``).
        row_limit: Optional ``LIMIT n`` cap. Defaults to no limit (full
            table). Use for sanity checks before a real ingestion.
        timeout: Max seconds to wait for the statement to terminate.

    Yields:
        Dict rows keyed by column name. All values are strings (JSON_ARRAY
        format); cast on the caller side using ``map_databricks_type_to_spark``.

    Raises:
        DatabricksSqlIngestError: on HTTP error, timeout, or non-success
            state from the API.
    """
    base = _normalise_host(host)
    statement = f"SELECT * FROM {source_table}"
    if row_limit is not None:
        statement += f" LIMIT {int(row_limit)}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # 1) Submit the statement.
    submit_payload = {
        "statement": statement,
        "warehouse_id": warehouse_id,
        "format": "JSON_ARRAY",
        "disposition": "INLINE",
        "wait_timeout": "0s",  # async: poll
    }
    submit_resp = _http_json(
        method="POST",
        url=f"{base}/api/2.0/sql/statements",
        headers=headers,
        body=submit_payload,
    )
    statement_id = submit_resp.get("statement_id")
    if not statement_id:
        raise DatabricksSqlIngestError(
            f"submit response missing statement_id: {submit_resp}"
        )

    # 2) Poll until terminal.
    deadline = time.monotonic() + timeout
    final = submit_resp
    while True:
        state = ((final.get("status") or {}).get("state") or "").upper()
        if state in ("SUCCEEDED", "FAILED", "CANCELED", "CLOSED"):
            break
        if time.monotonic() > deadline:
            raise DatabricksSqlIngestError(
                f"timeout after {timeout}s waiting for statement {statement_id} "
                f"(last state: {state})"
            )
        time.sleep(_POLL_INTERVAL_SECONDS)
        final = _http_json(
            method="GET",
            url=f"{base}/api/2.0/sql/statements/{statement_id}",
            headers=headers,
        )

    state = ((final.get("status") or {}).get("state") or "").upper()
    if state != "SUCCEEDED":
        err = (final.get("status") or {}).get("error", {}).get("message", "(no error message)")
        raise DatabricksSqlIngestError(
            f"statement {statement_id} ended in state {state}: {err}"
        )

    # 3) Extract schema (column names) + first chunk.
    manifest = final.get("manifest") or {}
    schema_columns = (manifest.get("schema") or {}).get("columns") or []
    column_names = [c.get("name") for c in schema_columns]

    result = final.get("result") or {}
    yield from _yield_chunk_rows(result.get("data_array") or [], column_names)

    # 4) Page through remaining chunks if present.
    chunks = (manifest.get("chunks") or [])
    for chunk in chunks[1:]:
        chunk_index = chunk.get("chunk_index")
        if chunk_index is None:
            continue
        chunk_resp = _http_json(
            method="GET",
            url=f"{base}/api/2.0/sql/statements/{statement_id}/result/chunks/{chunk_index}",
            headers=headers,
        )
        yield from _yield_chunk_rows(chunk_resp.get("data_array") or [], column_names)


# ---------------------------------------------------------------------------
# Helpers (private)
# ---------------------------------------------------------------------------

def _normalise_host(host: str) -> str:
    """Strip trailing slash, ensure https:// scheme."""
    host = host.strip().rstrip("/")
    if not host.startswith("http://") and not host.startswith("https://"):
        host = f"https://{host}"
    return host


def _http_json(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    body: dict | None = None,
) -> dict:
    """Stdlib-only HTTP request returning parsed JSON. Raises on HTTPError."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            payload = resp.read()
    except urllib.error.HTTPError as exc:
        # Read the body for richer error reporting.
        try:
            err_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = ""
        raise DatabricksSqlIngestError(
            f"HTTP {exc.code} on {method} {url}: {err_body[:512]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise DatabricksSqlIngestError(f"network error on {method} {url}: {exc}") from exc

    try:
        return json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise DatabricksSqlIngestError(
            f"non-JSON response from {url}: {payload[:512]!r}"
        ) from exc


def _yield_chunk_rows(
    data_array: list[list[Any]],
    column_names: list[str],
) -> Iterator[dict[str, Any]]:
    """Convert a list-of-lists chunk into dict rows keyed by column."""
    for row in data_array:
        yield {column_names[i]: row[i] for i in range(min(len(column_names), len(row)))}
