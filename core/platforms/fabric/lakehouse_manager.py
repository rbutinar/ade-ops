"""Fabric Lakehouse manager — provision lakehouses + read SQL endpoint props.

A Lakehouse in Fabric exposes two faces:
1. **Files / Tables** for Spark / notebook access (OneLake-backed)
2. **SQL Endpoint** for T-SQL access — used by Power BI DirectLake, Warehouse
   pipeline activities, and any non-Spark consumer.

This manager covers the create/inspect lifecycle. Table-level operations
(list tables in the lakehouse, schema introspection) hit a different
``/tables`` sub-API; included here for the demo's validation step.

There is no prior art in the ADE workshop for create — only
``ade_app/platforms/fabric/extractors/lakehouse_extractor.py`` for read.
This module is therefore net-new code (using only the existing
``FabricClient`` low-level primitives).
"""

from __future__ import annotations

import time

from core.connectors.fabric import FabricClient

LAKEHOUSE_ITEM_TYPE = "Lakehouse"

# When a brand-new lakehouse is created, its SQL endpoint provisioning is
# asynchronous and can take ~30-90 seconds. The get_item response will not
# contain the SQL endpoint connection string immediately. Poll for it.
SQL_ENDPOINT_POLL_INITIAL_WAIT = 5
SQL_ENDPOINT_POLL_MAX_WAIT = 20
SQL_ENDPOINT_POLL_TIMEOUT = 180


class FabricLakehouseManager:
    """High-level lakehouse operations bound to one workspace."""

    def __init__(self, client: FabricClient, workspace_id: str):
        self.client = client
        self.workspace_id = workspace_id

    # -- Inventory ------------------------------------------------------------

    def list_lakehouses(self) -> list[dict]:
        return self.client.list_items(self.workspace_id, item_type=LAKEHOUSE_ITEM_TYPE)

    def find_lakehouse(self, display_name: str) -> dict | None:
        return self.client.find_item_by_name(
            self.workspace_id,
            item_type=LAKEHOUSE_ITEM_TYPE,
            display_name=display_name,
        )

    def get_lakehouse(self, lakehouse_id: str) -> dict:
        """Get the lakehouse item with full properties (includes SQL endpoint)."""
        # The /lakehouses/{id} endpoint returns the full properties block,
        # which the generic /items/{id} does not always include.
        resp = self.client._request(
            "GET",
            f"/workspaces/{self.workspace_id}/lakehouses/{lakehouse_id}",
        )
        resp.raise_for_status()
        return resp.json()

    # -- Lifecycle ------------------------------------------------------------

    def create(
        self,
        display_name: str,
        *,
        description: str | None = None,
        enable_schemas: bool = False,
    ) -> dict:
        """Create a Lakehouse.

        ``enable_schemas`` enables the multi-schema preview ("Schemas in
        Lakehouse") — keep False unless the demo explicitly leverages it.
        """
        body: dict = {
            "displayName": display_name,
            "type": LAKEHOUSE_ITEM_TYPE,
        }
        if description is not None:
            body["description"] = description
        if enable_schemas:
            body["creationPayload"] = {"enableSchemas": True}
        resp = self.client._request(
            "POST", f"/workspaces/{self.workspace_id}/items", json=body
        )
        # Lakehouse creation may be sync (201) or async (202).
        if resp.status_code == 202:
            location = resp.headers.get("Location")
            if not location:
                raise RuntimeError(
                    "Fabric create lakehouse returned 202 without a Location header."
                )
            poll_resp = self.client._poll_lro(location)
            poll_resp.raise_for_status()
            body_payload = poll_resp.json() if poll_resp.content else {}
            if body_payload.get("status") == "Succeeded" or "id" not in body_payload:
                result_url = location.rstrip("/") + "/result"
                result_resp = self.client._request("GET", result_url)
                result_resp.raise_for_status()
                return result_resp.json()
            return body_payload
        resp.raise_for_status()
        return resp.json()

    def ensure_lakehouse(
        self,
        display_name: str,
        *,
        description: str | None = None,
        enable_schemas: bool = False,
    ) -> dict:
        existing = self.find_lakehouse(display_name)
        if existing is not None:
            return existing
        return self.create(
            display_name,
            description=description,
            enable_schemas=enable_schemas,
        )

    def delete(self, lakehouse_id: str) -> bool:
        resp = self.client._request(
            "DELETE",
            f"/workspaces/{self.workspace_id}/items/{lakehouse_id}",
        )
        return resp.status_code in (200, 204)

    # -- SQL endpoint ---------------------------------------------------------

    def get_sql_endpoint(self, lakehouse_id: str) -> dict:
        """Return ``{connection_string, id}`` for the lakehouse's SQL endpoint.

        Polls until the endpoint is provisioned (new lakehouses take seconds
        to minutes to expose it). Raises ``TimeoutError`` if not ready within
        ``SQL_ENDPOINT_POLL_TIMEOUT``.
        """
        wait = SQL_ENDPOINT_POLL_INITIAL_WAIT
        deadline = time.monotonic() + SQL_ENDPOINT_POLL_TIMEOUT
        while time.monotonic() < deadline:
            payload = self.get_lakehouse(lakehouse_id)
            properties = payload.get("properties") or {}
            sql_ep = properties.get("sqlEndpointProperties") or {}
            conn = sql_ep.get("connectionString")
            ep_id = sql_ep.get("id")
            provisioning = sql_ep.get("provisioningStatus")
            if conn and ep_id and provisioning in (None, "Success"):
                return {"connection_string": conn, "id": ep_id, "raw": sql_ep}
            time.sleep(wait)
            wait = min(int(wait * 1.5), SQL_ENDPOINT_POLL_MAX_WAIT)
        raise TimeoutError(
            f"SQL endpoint for lakehouse {lakehouse_id} not provisioned within "
            f"{SQL_ENDPOINT_POLL_TIMEOUT}s"
        )

    # -- Tables ---------------------------------------------------------------

    def list_tables(self, lakehouse_id: str) -> list[dict]:
        """List tables in a lakehouse. Returns ``[]`` if the lakehouse is empty."""
        resp = self.client._request(
            "GET",
            f"/workspaces/{self.workspace_id}/lakehouses/{lakehouse_id}/tables",
        )
        resp.raise_for_status()
        return resp.json().get("data", [])

    # -- Notebook attachment --------------------------------------------------

    @staticmethod
    def inject_default_lakehouse(
        notebook_content: dict,
        *,
        lakehouse_id: str,
        lakehouse_name: str,
        workspace_id: str,
    ) -> dict:
        """Return a copy of ``notebook_content`` with default-lakehouse metadata.

        Fabric notebook ipynb files carry their lakehouse binding in
        ``metadata.dependencies.lakehouse``. Without this binding the user has
        to attach the lakehouse manually in the UI before running. Injecting
        it here makes the deployed notebook usable on first open.

        Callers re-deploy the modified notebook via ``FabricNotebookManager``
        (this method does not perform a REST call; it's a pure transform so
        it can be chained into a convert→inject→deploy pipeline).
        """
        nb = dict(notebook_content)
        metadata = dict(nb.get("metadata", {}))
        dependencies = dict(metadata.get("dependencies", {}))
        dependencies["lakehouse"] = {
            "default_lakehouse": lakehouse_id,
            "default_lakehouse_name": lakehouse_name,
            "default_lakehouse_workspace_id": workspace_id,
        }
        metadata["dependencies"] = dependencies
        nb["metadata"] = metadata
        return nb
