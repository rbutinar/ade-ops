"""Fabric notebook manager — convenience layer over ``FabricClient``.

Bound to a single workspace (passed at construction). Reuses the existing
``FabricClient`` methods for list/find/create/update operations, including
the LRO polling for updateDefinition — no duplicate REST or auth logic.

The notebook payload format is ipynb v4 (the same dict shape produced by
``core.parsers.databricks_to_ipynb.convert_source``). The manager wraps it
in the InlineBase64 part structure that Fabric expects.

Prior art: ``ade_app/platforms/fabric/notebooks/manager.py`` in the ADE
workshop. That implementation hand-rolled its own HTTP client, 401 refresh
loop, LRO polling, and module-level convenience functions that re-built a
manager per call. The refactor here drops all of that in favor of the
``FabricClient`` already in ``core.connectors.fabric``.
"""

from __future__ import annotations

import base64
import json

from core.connectors.fabric import FabricClient

NOTEBOOK_ITEM_TYPE = "Notebook"
FOLDER_ITEM_TYPE = "Folder"
NOTEBOOK_PART_PATH = "notebook-content.ipynb"


def _encode_notebook(notebook: dict) -> str:
    """Encode an ipynb v4 dict to base64 string for InlineBase64 parts."""
    body = json.dumps(notebook, ensure_ascii=False)
    return base64.b64encode(body.encode("utf-8")).decode("ascii")


def _ipynb_definition(notebook: dict) -> dict:
    """Build the ``definition`` block Fabric expects for a Notebook item."""
    return {
        "format": "ipynb",
        "parts": [
            {
                "path": NOTEBOOK_PART_PATH,
                "payload": _encode_notebook(notebook),
                "payloadType": "InlineBase64",
            }
        ],
    }


class FabricNotebookManager:
    """High-level notebook operations bound to one workspace.

    Pass an already-authenticated ``FabricClient`` and a ``workspace_id``.
    """

    def __init__(self, client: FabricClient, workspace_id: str):
        self.client = client
        self.workspace_id = workspace_id

    # -- Inventory ------------------------------------------------------------

    def list_notebooks(self) -> list[dict]:
        return self.client.list_items(self.workspace_id, item_type=NOTEBOOK_ITEM_TYPE)

    def find_notebook(self, display_name: str) -> dict | None:
        return self.client.find_item_by_name(
            self.workspace_id,
            item_type=NOTEBOOK_ITEM_TYPE,
            display_name=display_name,
        )

    def list_folders(self) -> list[dict]:
        return self.client.list_items(self.workspace_id, item_type=FOLDER_ITEM_TYPE)

    def find_folder(self, display_name: str) -> dict | None:
        return self.client.find_item_by_name(
            self.workspace_id,
            item_type=FOLDER_ITEM_TYPE,
            display_name=display_name,
        )

    # -- Read -----------------------------------------------------------------

    def get_definition(self, notebook_id: str) -> dict:
        """Return the full ``getDefinition`` payload (with the ``definition`` key)."""
        return self.client.get_item_definition(
            self.workspace_id, notebook_id, format="ipynb"
        )

    def get_notebook_content(self, notebook_id: str) -> dict:
        """Decode the ipynb v4 dict out of a notebook's Fabric definition."""
        defn = self.get_definition(notebook_id)
        parts = defn.get("definition", {}).get("parts", [])
        for part in parts:
            if part.get("path") == NOTEBOOK_PART_PATH:
                blob = base64.b64decode(part["payload"])
                return json.loads(blob.decode("utf-8"))
        raise ValueError(
            f"notebook {notebook_id} has no '{NOTEBOOK_PART_PATH}' part in its definition"
        )

    # -- Deploy ---------------------------------------------------------------

    def create(
        self,
        display_name: str,
        notebook_content: dict,
        *,
        description: str | None = None,
    ) -> dict:
        return self.client.create_item(
            self.workspace_id,
            display_name=display_name,
            item_type=NOTEBOOK_ITEM_TYPE,
            definition=_ipynb_definition(notebook_content),
        )

    def update(self, notebook_id: str, notebook_content: dict) -> bool:
        return self.client.update_item_definition(
            self.workspace_id, notebook_id, _ipynb_definition(notebook_content)
        )

    def deploy(
        self,
        display_name: str,
        notebook_content: dict,
        *,
        folder_name: str | None = None,
    ) -> dict:
        """Idempotently deploy a notebook to the workspace.

        - If a notebook with ``display_name`` exists, update its definition.
        - Otherwise create it.
        - If ``folder_name`` is provided and the folder exists in the
          workspace, move the notebook there. A missing folder is logged but
          not blocking (deployment to root succeeds).

        Returns the resulting notebook item dict (post-deploy, possibly post-move).
        """
        existing = self.find_notebook(display_name)
        if existing is not None:
            notebook_id = existing["id"]
            self.update(notebook_id, notebook_content)
        else:
            created = self.create(display_name, notebook_content)
            notebook_id = created["id"]

        if folder_name:
            folder = self.find_folder(folder_name)
            if folder is not None:
                self.move_to_folder(notebook_id, folder["id"])

        # Re-fetch for current folderId etc.
        return self.client.get_item(self.workspace_id, notebook_id)

    # -- Organize -------------------------------------------------------------

    def rename(self, notebook_id: str, new_display_name: str) -> dict:
        resp = self.client._request(
            "PATCH",
            f"/workspaces/{self.workspace_id}/items/{notebook_id}",
            json={"displayName": new_display_name},
        )
        resp.raise_for_status()
        return resp.json()

    def move_to_folder(self, notebook_id: str, folder_id: str) -> bool:
        resp = self.client._request(
            "POST",
            f"/workspaces/{self.workspace_id}/items/{notebook_id}/move",
            json={"targetFolderId": folder_id},
        )
        return resp.status_code in (200, 202, 204)

    def delete(self, notebook_id: str) -> bool:
        resp = self.client._request(
            "DELETE",
            f"/workspaces/{self.workspace_id}/items/{notebook_id}",
        )
        return resp.status_code in (200, 204)
