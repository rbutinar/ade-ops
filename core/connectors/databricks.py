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
        success, msg = self.client.import_notebook(
            text_content, remote_path, is_notebook=is_notebook
        )
        if not success:
            print(f"  [ERROR] {msg[:200]}")
        return success

    def get_hash(self, remote_path: str) -> str | None:
        """Get hash by downloading content (Databricks has no native hash API)."""
        content = self.client.export_notebook(remote_path)
        if content is None:
            return None
        return f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]}"

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
