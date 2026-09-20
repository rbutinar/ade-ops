"""Fabric Warehouse connector for ade-ops.

Handles the T-SQL plane of Microsoft Fabric — i.e. the SQL endpoint exposed
by a Fabric Warehouse — over pyodbc with Azure AD authentication.

This is distinct from :mod:`core.connectors.fabric`, which targets the
**REST API plane** of Fabric (items, workspaces, getDefinition). The two
connectors complement each other and projects can use both for different
scopes.

Authentication options (chosen by credentials.yaml ``fabric_warehouse.auth_method``):

1. ``msal`` (default) — interactive browser via :mod:`msal_cache`, persistent
   on-disk token, ideal for local development.
2. ``service_principal`` — client id/secret/tenant, ideal for CI.

The connector implements :class:`core.connectors.base.PlatformConnector`
for scope ``fabric_warehouse``. ``list_objects`` returns views, procedures,
and tables across the configured schemas; ``pull_object`` returns the DDL of
a single object; ``push_object`` deploys a SQL file (DDL or DML).
"""

from __future__ import annotations

import hashlib
import struct
from datetime import datetime, timezone
from typing import Iterable

try:  # pyodbc is a runtime-optional dep — only required when this connector is used
    import pyodbc  # type: ignore
except ImportError:  # pragma: no cover
    pyodbc = None  # type: ignore

from ..platforms.fabric.auth import msal_cache


# =============================================================================
# Authentication helpers
# =============================================================================

def _pack_token_struct(token: str) -> bytes:
    """Pack a raw AAD token for the pyodbc ``attrs_before`` SQL_COPT_SS_ACCESS_TOKEN."""
    token_bytes = token.encode("utf-16-le")
    return struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)


def _resolve_sql_token(auth_config: dict) -> bytes:
    """Get an AAD access token packed for pyodbc, based on ``auth_config``."""
    method = auth_config.get("auth_method", "msal")
    tenant = auth_config.get("tenant_id") or auth_config.get("tenant")
    login_hint = auth_config.get("login_hint")

    if method == "msal":
        token_struct, token = msal_cache.get_sql_token_struct(
            tenant=tenant, login_hint=login_hint,
        )
        if not token:
            raise RuntimeError(
                "Fabric Warehouse MSAL auth failed (no token). "
                "Run `python -m core.platforms.fabric.auth.msal_cache --sql --tenant ...` to debug."
            )
        return token_struct

    if method == "service_principal":
        client_id = auth_config.get("client_id")
        client_secret = auth_config.get("client_secret")
        if not (client_id and client_secret and tenant):
            raise ValueError(
                "service_principal auth requires client_id, client_secret, tenant_id "
                "in credentials.yaml fabric_warehouse section."
            )
        import msal  # lazy
        app = msal.ConfidentialClientApplication(
            client_id=client_id,
            client_credential=client_secret,
            authority=f"https://login.microsoftonline.com/{tenant}",
        )
        result = app.acquire_token_for_client(scopes=["https://database.windows.net/.default"])
        token = result.get("access_token")
        if not token:
            err = result.get("error_description") or result.get("error") or "unknown"
            raise RuntimeError(f"Fabric Warehouse SP auth failed: {err}")
        return _pack_token_struct(token)

    raise ValueError(f"Unknown fabric_warehouse auth_method: {method!r}")


# =============================================================================
# pyodbc client
# =============================================================================

class FabricWarehouseClient:
    """Thin pyodbc wrapper for a Fabric Warehouse SQL endpoint."""

    SQL_COPT_SS_ACCESS_TOKEN = 1256  # ODBC attribute id for the AAD access token

    def __init__(
        self,
        *,
        server: str,
        database: str,
        auth_config: dict,
        driver: str = "ODBC Driver 17 for SQL Server",
    ):
        if pyodbc is None:
            raise RuntimeError(
                "pyodbc is required for the Fabric Warehouse connector. "
                "Install it: `pip install pyodbc` (and the matching ODBC driver)."
            )
        self.server = server
        self.database = database
        self.driver = driver
        self.auth_config = auth_config
        self._conn: pyodbc.Connection | None = None

    def connect(self) -> pyodbc.Connection:
        """Open (and cache) a pyodbc connection."""
        if self._conn is not None:
            return self._conn
        token_struct = _resolve_sql_token(self.auth_config)
        conn_str = (
            f"Driver={{{self.driver}}};"
            f"Server={self.server};"
            f"Database={self.database};"
            "Encrypt=yes;TrustServerCertificate=no;"
        )
        self._conn = pyodbc.connect(
            conn_str,
            attrs_before={self.SQL_COPT_SS_ACCESS_TOKEN: token_struct},
        )
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass
            self._conn = None

    def fetch(self, sql: str, params: tuple = ()) -> list[tuple]:
        """Execute ``sql`` and fetch all rows."""
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute(sql, params)
        return cursor.fetchall()

    def fetch_dicts(self, sql: str, params: tuple = ()) -> list[dict]:
        """Execute ``sql`` and return rows as dicts keyed by column name."""
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute(sql, params)
        cols = [c[0] for c in cursor.description] if cursor.description else []
        return [dict(zip(cols, row)) for row in cursor.fetchall()]

    def execute_batches(self, sql: str) -> int:
        """Execute a script containing one or more T-SQL batches separated by ``GO``.

        Returns the number of batches executed successfully. Stops on first error.
        """
        conn = self.connect()
        cursor = conn.cursor()
        batches = _split_go(sql)
        executed = 0
        for batch in batches:
            if not batch.strip():
                continue
            cursor.execute(batch)
            executed += 1
        conn.commit()
        return executed


def _split_go(sql: str) -> list[str]:
    """Split a T-SQL script on standalone ``GO`` lines (case-insensitive)."""
    out: list[str] = []
    current: list[str] = []
    for line in sql.splitlines():
        if line.strip().upper() == "GO":
            out.append("\n".join(current))
            current = []
        else:
            current.append(line)
    if current:
        out.append("\n".join(current))
    return out


# =============================================================================
# Connector
# =============================================================================

_DEFAULT_SCHEMAS = ("dbo",)
_DEFAULT_OBJECT_TYPES = ("VIEW", "PROCEDURE", "TABLE")


class FabricWarehouseConnector:
    """ade-ops connector for Microsoft Fabric Warehouse.

    Implements :class:`core.connectors.base.PlatformConnector` for scope
    ``fabric_warehouse``. Operates on views, procedures, and tables in the
    schemas listed in the overlay.
    """

    def __init__(self, client: FabricWarehouseClient):
        self.client = client

    @classmethod
    def from_credentials(cls, credentials: dict) -> FabricWarehouseConnector:
        cfg = credentials.get("fabric_warehouse")
        if not cfg:
            raise ValueError(
                "credentials.yaml has no 'fabric_warehouse' section. "
                "Add: fabric_warehouse.server, fabric_warehouse.database, "
                "fabric_warehouse.auth_method (msal | service_principal), tenant_id."
            )
        server = cfg.get("server")
        database = cfg.get("database")
        if not (server and database):
            raise ValueError(
                "fabric_warehouse credentials must include 'server' and 'database'."
            )
        client = FabricWarehouseClient(
            server=server, database=database, auth_config=cfg,
        )
        return cls(client)

    # ------------------------------------------------------------------ list
    def list_objects(
        self,
        env_config: dict,
        overlay: dict,
        *,
        pipeline_filter: str | None = None,
    ) -> list[dict]:
        """List views, procedures, tables across the configured schemas."""
        wh = overlay.get("fabric_warehouse") or {}
        schemas = wh.get("schemas") or _DEFAULT_SCHEMAS
        types = tuple(t.upper() for t in (wh.get("object_types") or _DEFAULT_OBJECT_TYPES))

        result: list[dict] = []
        for schema in schemas:
            if "VIEW" in types:
                result.extend(self._list_modules(schema, "VIEW", pipeline_filter))
            if "PROCEDURE" in types:
                result.extend(self._list_modules(schema, "PROCEDURE", pipeline_filter))
            if "TABLE" in types:
                result.extend(self._list_tables(schema, pipeline_filter))
        return result

    def _list_modules(
        self, schema: str, obj_type: str, name_filter: str | None,
    ) -> Iterable[dict]:
        """List views or procedures with their DDL."""
        sys_table = "sys.views" if obj_type == "VIEW" else "sys.procedures"
        rows = self.client.fetch_dicts(
            f"""
            SELECT
                SCHEMA_NAME(o.schema_id) AS schema_name,
                o.name AS object_name,
                o.create_date,
                o.modify_date
            FROM {sys_table} AS o
            WHERE SCHEMA_NAME(o.schema_id) = ?
            ORDER BY o.name
            """,
            (schema,),
        )
        out: list[dict] = []
        for row in rows:
            name = row["object_name"]
            if name_filter and name_filter not in name:
                continue
            local_rel = f"{schema}/{obj_type.lower()}s/{name}.sql"
            remote = f"{schema}|{name}|{obj_type}"
            out.append({
                "path": remote,
                "local_path": local_rel,
                "type": obj_type,
                "modified": (row.get("modify_date") or row.get("create_date") or
                             datetime.now(timezone.utc)).isoformat()
                            if hasattr(row.get("modify_date") or row.get("create_date") or 0, "isoformat")
                            else str(row.get("modify_date") or ""),
            })
        return out

    def _list_tables(self, schema: str, name_filter: str | None) -> Iterable[dict]:
        rows = self.client.fetch_dicts(
            """
            SELECT TABLE_SCHEMA, TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE = 'BASE TABLE' AND TABLE_SCHEMA = ?
            ORDER BY TABLE_NAME
            """,
            (schema,),
        )
        out: list[dict] = []
        for row in rows:
            name = row["TABLE_NAME"]
            if name_filter and name_filter not in name:
                continue
            local_rel = f"{schema}/tables/{name}.sql"
            remote = f"{schema}|{name}|TABLE"
            out.append({
                "path": remote,
                "local_path": local_rel,
                "type": "TABLE",
                "modified": datetime.now(timezone.utc).isoformat(),
            })
        return out

    # ------------------------------------------------------------------ pull
    def pull_object(self, remote_path: str) -> str | None:
        try:
            schema, name, obj_type = remote_path.split("|")
        except ValueError:
            return None

        if obj_type in ("VIEW", "PROCEDURE"):
            rows = self.client.fetch(
                """
                SELECT m.definition
                FROM sys.objects AS o
                JOIN sys.sql_modules AS m ON o.object_id = m.object_id
                WHERE SCHEMA_NAME(o.schema_id) = ? AND o.name = ?
                """,
                (schema, name),
            )
            if rows:
                return rows[0][0]
            return None

        if obj_type == "TABLE":
            # Synthesize a CREATE TABLE statement from INFORMATION_SCHEMA.
            cols = self.client.fetch_dicts(
                """
                SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH,
                       NUMERIC_PRECISION, NUMERIC_SCALE, IS_NULLABLE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
                ORDER BY ORDINAL_POSITION
                """,
                (schema, name),
            )
            if not cols:
                return None
            return _format_create_table(schema, name, cols)
        return None

    # ------------------------------------------------------------------ push
    def push_object(
        self,
        local_path: str,
        content: bytes,
        env_config: dict,
        overlay: dict,
    ) -> bool:
        """Execute a SQL script (DDL/DML), splitting on standalone GO lines."""
        try:
            sql = content.decode("utf-8")
        except UnicodeDecodeError:
            return False
        try:
            self.client.execute_batches(sql)
        except Exception as e:  # noqa: BLE001
            print(f"  [ERROR] {local_path}: {e}")
            return False
        return True

    def get_hash(self, remote_path: str) -> str | None:
        content = self.pull_object(remote_path)
        if content is None:
            return None
        return f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]}"


# =============================================================================
# Helpers
# =============================================================================

def _format_create_table(schema: str, name: str, cols: list[dict]) -> str:
    """Generate a CREATE TABLE statement from INFORMATION_SCHEMA columns."""
    lines = [f"CREATE TABLE {schema}.{name} ("]
    parts: list[str] = []
    for c in cols:
        col_name = c["COLUMN_NAME"]
        dt = c["DATA_TYPE"]
        max_len = c.get("CHARACTER_MAXIMUM_LENGTH")
        precision = c.get("NUMERIC_PRECISION")
        scale = c.get("NUMERIC_SCALE")
        if dt in ("varchar", "nvarchar", "char", "nchar") and max_len:
            type_str = f"{dt}({max_len if max_len > 0 else 'MAX'})"
        elif dt in ("decimal", "numeric") and precision is not None:
            type_str = f"{dt}({precision},{scale or 0})"
        else:
            type_str = dt
        nullable = "" if c.get("IS_NULLABLE") == "YES" else " NOT NULL"
        parts.append(f"    {col_name} {type_str}{nullable}")
    lines.append(",\n".join(parts))
    lines.append(");")
    return "\n".join(lines)
