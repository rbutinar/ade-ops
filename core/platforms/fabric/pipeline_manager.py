"""Fabric Data Pipeline manager — orchestration over ``FabricClient``.

Bound to a single workspace. Exposes:
- inventory (``list_pipelines``, ``find_pipeline``)
- lifecycle (``create``, ``update_definition``, ``deploy``, ``delete``)
- definition builders (``build_notebook_activity``, ``build_pipeline_definition``)
- execution (``run``, ``poll_run``)

The pipeline definition format mirrors what Fabric stores under
``pipeline-content.json`` — root shape ``{"properties": {"activities": [...]}}``.
The notebook orchestration activity has type ``TridentNotebook`` with
``typeProperties.notebookId`` + ``typeProperties.workspaceId``.

Prior art: ``ade_app/platforms/fabric/pipelines/manager.py`` (ADE workshop)
which only handled create/get/update + Coesia/Asahi project scripts which
hand-rolled the run path. This refactor consolidates everything into one
class using the existing ``FabricClient`` for REST and provides the
notebook-activity builder so callers don't need to know the JSON shape.
"""

from __future__ import annotations

import base64
import json
import time

from core.connectors.fabric import FabricClient

PIPELINE_ITEM_TYPE = "DataPipeline"
PIPELINE_PART_PATH = "pipeline-content.json"

# Default activity policy. Aligns with the Coesia/Asahi real-world deploys
# and the Fabric UI defaults. Overridable per call.
DEFAULT_ACTIVITY_POLICY: dict = {
    "timeout": "0.12:00:00",
    "retry": 0,
    "retryIntervalInSeconds": 30,
    "secureOutput": False,
    "secureInput": False,
}

# Run polling parameters — pipeline runs can take minutes; the default
# timeout is generous but configurable per call.
RUN_POLL_INITIAL_WAIT = 5
RUN_POLL_MAX_WAIT = 30
RUN_POLL_DEFAULT_TIMEOUT = 1800  # 30 min


def _encode_pipeline_definition_body(definition: dict) -> str:
    body = json.dumps(definition, ensure_ascii=False)
    return base64.b64encode(body.encode("utf-8")).decode("ascii")


def _pipeline_definition_part(definition: dict) -> dict:
    return {
        "parts": [
            {
                "path": PIPELINE_PART_PATH,
                "payload": _encode_pipeline_definition_body(definition),
                "payloadType": "InlineBase64",
            }
        ]
    }


class FabricPipelineManager:
    """High-level Data Pipeline operations bound to one workspace."""

    def __init__(self, client: FabricClient, workspace_id: str):
        self.client = client
        self.workspace_id = workspace_id

    # -- Inventory ------------------------------------------------------------

    def list_pipelines(self) -> list[dict]:
        return self.client.list_items(self.workspace_id, item_type=PIPELINE_ITEM_TYPE)

    def find_pipeline(self, display_name: str) -> dict | None:
        return self.client.find_item_by_name(
            self.workspace_id,
            item_type=PIPELINE_ITEM_TYPE,
            display_name=display_name,
        )

    # -- Read -----------------------------------------------------------------

    def get_definition(self, pipeline_id: str) -> dict:
        return self.client.get_item_definition(self.workspace_id, pipeline_id)

    def get_pipeline_body(self, pipeline_id: str) -> dict:
        """Decode the pipeline-content.json dict out of the Fabric definition."""
        defn = self.get_definition(pipeline_id)
        for part in defn.get("definition", {}).get("parts", []):
            if part.get("path") == PIPELINE_PART_PATH:
                return json.loads(base64.b64decode(part["payload"]).decode("utf-8"))
        raise ValueError(
            f"pipeline {pipeline_id} has no '{PIPELINE_PART_PATH}' part in its definition"
        )

    # -- Lifecycle ------------------------------------------------------------

    def create(
        self,
        display_name: str,
        *,
        definition: dict | None = None,
        description: str | None = None,
    ) -> dict:
        wrapped = _pipeline_definition_part(definition) if definition is not None else None
        return self.client.create_item(
            self.workspace_id,
            display_name=display_name,
            item_type=PIPELINE_ITEM_TYPE,
            definition=wrapped,
        )

    def update_definition(self, pipeline_id: str, definition: dict) -> bool:
        return self.client.update_item_definition(
            self.workspace_id,
            pipeline_id,
            _pipeline_definition_part(definition),
        )

    def deploy(self, display_name: str, definition: dict) -> dict:
        """Idempotent: update if exists, otherwise create."""
        existing = self.find_pipeline(display_name)
        if existing is not None:
            self.update_definition(existing["id"], definition)
            return self.client.get_item(self.workspace_id, existing["id"])
        return self.create(display_name, definition=definition)

    def delete(self, pipeline_id: str) -> bool:
        resp = self.client._request(
            "DELETE",
            f"/workspaces/{self.workspace_id}/items/{pipeline_id}",
        )
        return resp.status_code in (200, 204)

    # -- Definition builders --------------------------------------------------

    @staticmethod
    def build_notebook_activity(
        *,
        name: str,
        notebook_id: str,
        workspace_id: str,
        depends_on: list[str] | None = None,
        policy: dict | None = None,
    ) -> dict:
        """Build a ``TridentNotebook`` activity that runs a Fabric notebook.

        ``depends_on`` is a list of upstream activity ``name``s; each gets
        wrapped as ``{"activity": ..., "dependencyConditions": ["Succeeded"]}``.
        """
        depends = [
            {"activity": upstream, "dependencyConditions": ["Succeeded"]}
            for upstream in (depends_on or [])
        ]
        return {
            "name": name,
            "type": "TridentNotebook",
            "dependsOn": depends,
            "policy": policy or dict(DEFAULT_ACTIVITY_POLICY),
            "typeProperties": {
                "notebookId": notebook_id,
                "workspaceId": workspace_id,
            },
        }

    @staticmethod
    def build_pipeline_definition(activities: list[dict]) -> dict:
        """Wrap a list of activity dicts into the canonical pipeline body."""
        return {"properties": {"activities": activities}}

    # -- Execution ------------------------------------------------------------

    def run(self, pipeline_id: str) -> dict:
        """Trigger a pipeline run.

        Returns a job-info dict with ``location`` (poll URL), ``operation_id``,
        and ``retry_after`` (recommended poll interval in seconds).
        """
        resp = self.client._request(
            "POST",
            f"/workspaces/{self.workspace_id}/items/{pipeline_id}/jobs/instances",
            params={"jobType": "Pipeline"},
        )
        if resp.status_code not in (200, 201, 202):
            resp.raise_for_status()
        location = resp.headers.get("Location")
        operation_id = resp.headers.get("x-ms-operation-id")
        retry_after = resp.headers.get("Retry-After", str(RUN_POLL_INITIAL_WAIT))
        return {
            "status": "Accepted" if resp.status_code == 202 else "Started",
            "location": location,
            "operation_id": operation_id,
            "retry_after": int(retry_after),
        }

    def poll_run(
        self,
        job_info: dict,
        *,
        timeout_seconds: int = RUN_POLL_DEFAULT_TIMEOUT,
    ) -> dict:
        """Poll a running pipeline job until terminal or timeout.

        Returns a dict with ``status`` (``Succeeded`` / ``Failed`` /
        ``Cancelled`` / ``Timeout``) and the last full job payload under
        ``result``. Uses exponential backoff up to ``RUN_POLL_MAX_WAIT``.
        """
        location = job_info.get("location")
        if not location:
            return {"status": "Failed", "error": "no Location header on run response"}

        wait = max(job_info.get("retry_after", RUN_POLL_INITIAL_WAIT), 1)
        deadline = time.monotonic() + timeout_seconds
        last_body: dict = {}

        while time.monotonic() < deadline:
            time.sleep(wait)
            resp = self.client._request("GET", location)
            if resp.status_code == 200:
                try:
                    last_body = resp.json()
                except ValueError:
                    last_body = {}
                status = last_body.get("status")
                if status in ("Completed", "Succeeded"):
                    return {"status": "Succeeded", "result": last_body}
                if status in ("Failed", "Cancelled", "Deduped"):
                    return {
                        "status": status,
                        "result": last_body,
                        "error": last_body.get("failureReason") or last_body.get("error"),
                    }
                # NotStarted / InProgress — keep polling.
            elif resp.status_code != 202:
                resp.raise_for_status()
            wait = min(int(wait * 1.5), RUN_POLL_MAX_WAIT)

        return {"status": "Timeout", "result": last_body}
