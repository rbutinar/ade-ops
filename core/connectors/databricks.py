"""Databricks connector for ade-ops.

Handles Databricks REST API interactions:
- List workspace objects recursively
- Export notebooks and files (pull)
- Import notebooks and files (push)

Authentication: reads host/token from the project's credentials.yaml.
"""

from __future__ import annotations

import base64
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx


class DatabricksClient:
    """Databricks REST API client for workspace operations."""

    def __init__(self, host: str, token: str):
        self.host = host.rstrip("/")
        if not self.host.startswith("http"):
            self.host = f"https://{self.host}"
        self._client = httpx.Client(
            base_url=f"{self.host}/api/2.0",
            headers={"Authorization": f"Bearer {token}"},
            verify=True,
            timeout=30.0,
        )

    def current_user(self) -> dict:
        """Fetch the identity the token authenticates as (SCIM ``Me``).

        Returns the SCIM user payload; ``userName`` is the login email. Used by
        preflight to surface *who* a token resolves to before declaring a
        workspace healthy — a token silently inherited from ambient env vars can
        point a demo at a client's production workspace, and "reachable" alone
        does not reveal the identity (TICK-008).
        """
        resp = self._client.get("/preview/scim/v2/Me")
        resp.raise_for_status()
        return resp.json()

    def list_workspace(self, path: str) -> list[dict]:
        """List objects in a workspace directory."""
        resp = self._client.get("/workspace/list", params={"path": path})
        if resp.status_code == 200:
            return resp.json().get("objects", [])
        if resp.status_code == 404:
            return []
        resp.raise_for_status()

    def list_recursive(self, path: str) -> list[dict]:
        """List all objects recursively under a path."""
        result = []
        for obj in self.list_workspace(path):
            if obj.get("object_type") == "DIRECTORY":
                result.extend(self.list_recursive(obj["path"]))
            else:
                result.append(obj)
        return result

    def export_notebook(self, workspace_path: str) -> str | None:
        """Export notebook/file content as UTF-8 string."""
        resp = self._client.get(
            "/workspace/export",
            params={"path": workspace_path, "format": "SOURCE"},
        )
        if resp.status_code == 200:
            content = base64.b64decode(resp.json().get("content", "")).decode("utf-8")
            return content.replace("\r\n", "\n")
        return None

    def get_status(self, workspace_path: str) -> dict | None:
        """Return the workspace object's status (object_id, modified_at, ...), or None.

        Used to verify a push actually landed: a 200 OK on /workspace/import does
        not guarantee the workspace was updated (observed silent no-op), so callers
        compare ``modified_at`` before and after the import.
        """
        resp = self._client.get("/workspace/get-status", params={"path": workspace_path})
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 404:
            return None
        resp.raise_for_status()

    def import_notebook(
        self, content: str, workspace_path: str, *, is_notebook: bool = True
    ) -> tuple[bool, str]:
        """Upload content to workspace."""
        b64 = base64.b64encode(content.encode("utf-8")).decode("utf-8")
        payload = {
            "path": workspace_path,
            "content": b64,
            "overwrite": True,
        }
        if is_notebook:
            payload["format"] = "SOURCE"
            payload["language"] = "PYTHON"
        else:
            payload["format"] = "AUTO"

        resp = self._client.post("/workspace/import", json=payload, timeout=60.0)
        return resp.status_code == 200, resp.text

    def ensure_dir(self, dir_path: str) -> None:
        """Create workspace directory (recursive, idempotent).

        Raises RuntimeError on non-200 so callers see the underlying mkdirs
        error rather than a misleading RESOURCE_DOES_NOT_EXIST on the
        subsequent /workspace/import.
        """
        resp = self._client.post("/workspace/mkdirs", json={"path": dir_path})
        if resp.status_code != 200:
            raise RuntimeError(
                f"Databricks mkdirs failed for {dir_path!r}: "
                f"HTTP {resp.status_code} {resp.text[:300]}"
            )

    # --- Data operations (SQL warehouse + jobs runs) -----------------------
    # Power the REST fallback for /databricks-query and /databricks-run so
    # managed data ops work without the `databricks` MCP server. They use the
    # SQL Statement Execution API (2.0) and the Jobs API (2.1).

    def run_sql_statement(
        self,
        statement: str,
        warehouse_id: str,
        *,
        catalog: str | None = None,
        schema: str | None = None,
        poll_interval: float = 2.0,
        poll_timeout: float = 300.0,
    ) -> dict:
        """Execute a SQL statement and block until it terminates.

        Returns the final statement payload (status + manifest + result).
        Raises RuntimeError on a FAILED/CANCELED/CLOSED statement and
        TimeoutError if it does not terminate within ``poll_timeout``.
        """
        body: dict = {
            "statement": statement,
            "warehouse_id": warehouse_id,
            "wait_timeout": "30s",
            "format": "JSON_ARRAY",
            "disposition": "INLINE",
        }
        if catalog:
            body["catalog"] = catalog
        if schema:
            body["schema"] = schema

        resp = self._client.post("/sql/statements", json=body, timeout=60.0)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Databricks SQL statement submit failed: "
                f"HTTP {resp.status_code} {resp.text[:300]}"
            )
        payload = resp.json()
        statement_id = payload.get("statement_id", "")

        deadline = time.monotonic() + poll_timeout
        while True:
            state = (payload.get("status") or {}).get("state")
            if state == "SUCCEEDED":
                return payload
            if state in ("FAILED", "CANCELED", "CLOSED"):
                err = (payload.get("status") or {}).get("error", {})
                raise RuntimeError(
                    f"Databricks SQL statement {state}: "
                    f"{err.get('message', resp.text[:300])}"
                )
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Databricks SQL statement {statement_id} did not finish "
                    f"within {poll_timeout}s (last state {state})"
                )
            time.sleep(poll_interval)
            poll = self._client.get(f"/sql/statements/{statement_id}")
            poll.raise_for_status()
            payload = poll.json()

    def list_warehouses(self) -> list[dict]:
        """List SQL warehouses (REST ``GET /api/2.0/sql/warehouses``).

        Used to auto-discover a warehouse for /databricks-query when none is
        passed and the overlay does not declare one. The `databricks` MCP
        server's ``manage_sql_warehouse`` has no ``list`` action, so the REST
        endpoint is the only enumeration path.
        """
        resp = self._client.get("/sql/warehouses")
        resp.raise_for_status()
        return resp.json().get("warehouses", [])

    def submit_job_run(
        self,
        tasks: list[dict],
        run_name: str,
        *,
        timeout_seconds: int | None = None,
        poll_interval: float = 5.0,
        poll_timeout: float = 1800.0,
    ) -> dict:
        """Submit a one-time job run and block until it terminates.

        ``tasks`` follows the Jobs 2.1 ``runs/submit`` task spec (each task
        carries a ``notebook_task``/``spark_python_task``/... plus compute).
        Returns the final ``runs/get`` payload. Raises RuntimeError on a
        non-success terminal result and TimeoutError on poll exhaustion.
        """
        body: dict = {"run_name": run_name, "tasks": tasks}
        if timeout_seconds is not None:
            body["timeout_seconds"] = timeout_seconds

        resp = self._client.post(
            f"{self.host}/api/2.1/jobs/runs/submit", json=body, timeout=60.0
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Databricks job run submit failed: "
                f"HTTP {resp.status_code} {resp.text[:300]}"
            )
        run_id = resp.json().get("run_id")

        get_url = f"{self.host}/api/2.1/jobs/runs/get"
        deadline = time.monotonic() + poll_timeout
        terminal = {"TERMINATED", "SKIPPED", "INTERNAL_ERROR"}
        while True:
            poll = self._client.get(get_url, params={"run_id": run_id})
            poll.raise_for_status()
            run = poll.json()
            state = run.get("state", {})
            life = state.get("life_cycle_state")
            if life in terminal:
                result = state.get("result_state")
                if result != "SUCCESS":
                    raise RuntimeError(
                        f"Databricks run {run_id} {life}/{result}: "
                        f"{state.get('state_message', '')[:300]}"
                    )
                return run
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Databricks run {run_id} did not finish within "
                    f"{poll_timeout}s (last state {life})"
                )
            time.sleep(poll_interval)


class DatabricksConnector:
    """ade-ops connector for Databricks workspaces.

    Implements PlatformConnector protocol.
    """

    def __init__(self, host: str, token: str):
        self.client = DatabricksClient(host, token)

    @classmethod
    def from_credentials(
        cls, credentials: dict, host: str | None = None
    ) -> DatabricksConnector:
        """Create from credentials.yaml databricks section.

        ``host`` is conventionally declared in ``project.yaml`` under
        ``platforms.databricks.host`` (it identifies the workspace, not an
        identity) and is passed in by the caller. As a fallback, the
        method also accepts a ``host`` value embedded in the credentials
        section so legacy or single-file setups still work.
        """
        db = credentials.get("databricks", {})
        host = host or db.get("host", "")
        token = db.get("token", "")
        if not host or not token:
            raise ValueError(
                "Databricks connector requires both host and token. "
                "Host should be set in project.yaml under "
                "platforms.databricks.host (resolved via ${DATABRICKS_HOST} "
                "env var by default). Token should be in credentials.yaml "
                "under databricks.token (typically ${DATABRICKS_TOKEN})."
            )
        for label, val in (("host", host), ("token", token)):
            if isinstance(val, str) and "${" in val:
                start = val.find("${") + 2
                end = val.find("}", start)
                var = val[start:end] if end > start else "?"
                raise EnvironmentError(
                    f"Databricks credentials.{label} references unresolved env var "
                    f"'{var}'. Set it before running operations on the databricks scope "
                    f"(or use --scope power_bi if you only need Fabric)."
                )
        return cls(host, token)

    def list_objects(
        self,
        env_config: dict,
        overlay: dict,
        *,
        pipeline_filter: str | None = None,
    ) -> list[dict]:
        """List all notebooks/files in the workspace path."""
        db_overlay = overlay.get("databricks", {})
        ws_root = db_overlay.get("workspace_path", "")
        if not ws_root:
            # Fallback to env_config
            db_env = env_config.get("platforms", {}).get("databricks", {})
            ws_root = db_env.get("workspace_path", "")
        if not ws_root:
            raise ValueError("No workspace_path in overlay or environment config")

        # List top-level folders
        top_objects = self.client.list_workspace(ws_root)
        result = []

        # When pipeline_filter exactly matches a top-folder name, restrict the
        # recursion to that folder — fast path that avoids list_recursive on
        # every top folder. Otherwise enumerate everything and apply a
        # substring match on the relative path below, symmetric with push and
        # diff (operations.push / operations.diff use `file_filter in k`).
        top_folder_names = {
            obj["path"].split("/")[-1]
            for obj in top_objects
            if obj.get("object_type") == "DIRECTORY"
        }
        fast_path = pipeline_filter is not None and pipeline_filter in top_folder_names

        for obj in top_objects:
            if obj.get("object_type") == "DIRECTORY":
                folder_name = obj["path"].split("/")[-1]
                if fast_path and folder_name != pipeline_filter:
                    continue
                children = self.client.list_recursive(obj["path"])
                for child in children:
                    result.append(self._to_object_entry(child, ws_root))
            else:
                # Skip top-level files when fast_path matched a folder name —
                # they are by definition outside the matched folder. The
                # post-enumeration substring filter still applies for the
                # non-fast-path case.
                if fast_path:
                    continue
                result.append(self._to_object_entry(obj, ws_root))

        # Substring filter (post-enumeration) — applied when the fast path
        # didn't kick in. Matches against `local_path` (the relative path used
        # for state storage) so a filter like "gold_ft_registration_supplier.py"
        # picks the matching files regardless of which top folder they live in.
        if pipeline_filter and not fast_path:
            result = [r for r in result if pipeline_filter in r["local_path"]]

        return result

    def pull_object(self, remote_path: str) -> str | None:
        """Export a notebook/file from the workspace."""
        return self.client.export_notebook(remote_path)

    def push_object(
        self,
        local_path: str,
        content: bytes,
        env_config: dict,
        overlay: dict,
    ) -> bool:
        """Import a notebook/file to the workspace."""
        db_overlay = overlay.get("databricks", {})
        ws_root = db_overlay.get("workspace_path", "")
        if not ws_root:
            db_env = env_config.get("platforms", {}).get("databricks", {})
            ws_root = db_env.get("workspace_path", "")

        # Build remote path
        # Strip .py extension for notebooks (Databricks convention)
        remote_rel = local_path
        is_notebook = local_path.endswith(".py")
        if is_notebook:
            remote_rel = local_path[:-3]  # Remove .py

        remote_path = f"{ws_root}/{remote_rel}"

        # Ensure parent directory exists. Failures here are reported with
        # the underlying API error so the user doesn't get a misleading
        # RESOURCE_DOES_NOT_EXIST on the import call below.
        parent = "/".join(remote_path.split("/")[:-1])
        try:
            self.client.ensure_dir(parent)
        except RuntimeError as e:
            print(f"  [ERROR] {e}")
            return False

        text_content = content.decode("utf-8")
        # Capture the pre-import server timestamp so we can prove the import
        # actually landed. A 200 OK on /workspace/import does not guarantee the
        # workspace was updated (observed silent no-op): without this check a
        # stale notebook keeps running and the subsequent RUN is falsely green.
        before = self.client.get_status(remote_path)
        success, msg = self.client.import_notebook(
            text_content, remote_path, is_notebook=is_notebook
        )
        if not success:
            print(f"  [ERROR] {msg[:200]}")
            return False

        after = self.client.get_status(remote_path)
        if after is None:
            print(
                f"  [ERROR] import returned HTTP 200 but no object exists at "
                f"{remote_path} — silent no-op, push did not land"
            )
            return False
        before_mtime = (before or {}).get("modified_at")
        after_mtime = after.get("modified_at")
        if before is not None and before_mtime is not None and after_mtime == before_mtime:
            print(
                f"  [ERROR] import returned HTTP 200 but {remote_path} modified_at "
                f"is unchanged ({after_mtime}) — silent no-op, push did not land"
            )
            return False
        return True

    def get_hash(self, remote_path: str) -> str | None:
        """Get hash by downloading content (Databricks has no native hash API)."""
        content = self.client.export_notebook(remote_path)
        if content is None:
            return None
        return f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]}"

    def run_query(
        self,
        sql: str,
        warehouse_id: str,
        *,
        catalog: str | None = None,
        schema: str | None = None,
    ) -> dict:
        """Run a SQL query over REST and return normalized columns + rows.

        REST fallback for /databricks-query when the `databricks` MCP server is
        not configured. Returns ``{"columns": [...], "rows": [[...]],
        "row_count": int, "truncated": bool}``.
        """
        payload = self.client.run_sql_statement(
            sql, warehouse_id, catalog=catalog, schema=schema
        )
        manifest = payload.get("manifest") or {}
        columns = [
            c["name"] for c in (manifest.get("schema") or {}).get("columns", [])
        ]
        result = payload.get("result") or {}
        rows = result.get("data_array") or []
        return {
            "columns": columns,
            "rows": rows,
            "row_count": manifest.get("total_row_count", len(rows)),
            "truncated": bool(manifest.get("truncated", False)),
        }

    def pick_warehouse(self) -> str:
        """Pick the best available SQL warehouse id, or raise if none exist.

        Mirrors the MCP ``get_best_warehouse`` preference: a RUNNING warehouse
        first, then STARTING, otherwise the first declared one (it auto-starts
        on the first query). REST fallback for warehouse discovery.
        """
        warehouses = self.client.list_warehouses()
        if not warehouses:
            raise RuntimeError(
                "No SQL warehouses found on this workspace. Create one in the "
                "Databricks UI or pass --warehouse explicitly."
            )
        by_state: dict[str, list[dict]] = {}
        for w in warehouses:
            by_state.setdefault(w.get("state", ""), []).append(w)
        for state in ("RUNNING", "STARTING"):
            if by_state.get(state):
                return by_state[state][0]["id"]
        return warehouses[0]["id"]

    def run_notebook(
        self,
        notebook_path: str,
        *,
        existing_cluster_id: str | None = None,
        new_cluster: dict | None = None,
        base_parameters: dict | None = None,
        run_name: str | None = None,
        timeout_seconds: int | None = None,
    ) -> dict:
        """Run a single notebook as a one-time job run over REST.

        REST fallback for /databricks-run. Supply either ``existing_cluster_id``
        or a ``new_cluster`` spec. ``timeout_seconds`` is the job-side timeout
        (Databricks cancels the run if exceeded); the poll loop is given a small
        buffer over it so the client observes the cancellation. Returns the
        terminal ``runs/get`` payload.
        """
        if not existing_cluster_id and not new_cluster:
            raise ValueError(
                "run_notebook requires either existing_cluster_id or new_cluster"
            )
        task: dict = {
            "task_key": "run",
            "notebook_task": {"notebook_path": notebook_path},
        }
        if base_parameters:
            task["notebook_task"]["base_parameters"] = base_parameters
        if existing_cluster_id:
            task["existing_cluster_id"] = existing_cluster_id
        else:
            task["new_cluster"] = new_cluster
        submit_kwargs: dict = {}
        if timeout_seconds is not None:
            submit_kwargs["timeout_seconds"] = timeout_seconds
            submit_kwargs["poll_timeout"] = timeout_seconds + 120
        return self.client.submit_job_run(
            [task],
            run_name or f"ade-ops run: {notebook_path.split('/')[-1]}",
            **submit_kwargs,
        )

    @staticmethod
    def _to_object_entry(obj: dict, ws_root: str) -> dict:
        """Convert Databricks API object to standard entry."""
        remote_path = obj["path"]
        rel = remote_path[len(ws_root) + 1:]
        obj_type = obj.get("object_type", "FILE")

        # Add .py for notebooks (Databricks strips extensions)
        local_rel = f"{rel}.py" if obj_type == "NOTEBOOK" and not rel.endswith(".py") else rel

        return {
            "path": remote_path,
            "local_path": local_rel,
            "type": obj_type,
            "modified": datetime.now(timezone.utc).isoformat(),
        }
