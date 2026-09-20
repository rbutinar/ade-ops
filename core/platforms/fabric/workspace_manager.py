"""Fabric workspace manager — convenience layer over ``FabricClient``.

Composes a ``FabricClient`` (already authenticated) and exposes higher-level
operations: idempotent provisioning, capacity assignment, role membership.

Original prior art: ``ade_app/platforms/fabric/managers/workspace_manager.py``
in the ADE workshop, which used ``requests`` + msal directly and bundled
auth+credentials loading inside ``__init__``. This refactor uses ade-ops'
existing ``FabricClient`` + ``FabricAuthenticator`` for auth (no duplicate
token logic), httpx-based transport, and moves to the modern Fabric API
``roleAssignments`` endpoint instead of the legacy Power BI ``groups/users``.

Usage::

    from core.connectors.fabric import FabricAuthenticator, FabricClient
    from core.platforms.fabric.workspace_manager import FabricWorkspaceManager

    auth = FabricAuthenticator({"auth_method": "az_cli", "az_tenant_id": "..."})
    client = FabricClient(auth.get_token)
    manager = FabricWorkspaceManager(client)

    ws = manager.ensure_workspace("MyProject_DEV", capacity_id="...")
    manager.add_service_principal(ws["id"], app_id="...", role="Admin")
"""

from __future__ import annotations

from typing import Literal

from core.connectors.fabric import FabricAuthenticator, FabricClient


Role = Literal["Admin", "Member", "Contributor", "Viewer"]
PrincipalType = Literal["User", "Group", "ServicePrincipal"]


class FabricWorkspaceManager:
    """High-level workspace operations.

    Construct with an already-authenticated ``FabricClient`` (composition),
    or use the ``from_credentials`` classmethod for the convenience path.
    """

    def __init__(self, client: FabricClient):
        self.client = client

    @classmethod
    def from_credentials(
        cls,
        credentials: dict,
        *,
        env_platform_auth: dict | None = None,
    ) -> FabricWorkspaceManager:
        """Build a manager from a ``credentials.yaml``-style dict.

        Mirrors ``FabricConnector.from_credentials`` so callers can switch
        between the connector (item sync) and this manager (workspace ops)
        with the same auth surface.
        """
        fabric = credentials.get("fabric") or {}
        merged = dict(fabric)
        if env_platform_auth:
            override = dict(env_platform_auth)
            if "method" in override and "auth_method" not in override:
                override["auth_method"] = override.pop("method")
            merged.update({k: v for k, v in override.items() if v is not None})
        if not merged:
            raise ValueError(
                "No fabric auth config found. Provide either credentials.yaml "
                "fabric section or environments.{env}.platforms.fabric.auth "
                "in project.yaml."
            )
        auth = FabricAuthenticator(merged)
        return cls(FabricClient(auth.get_token))

    # -- Workspace lifecycle --------------------------------------------------

    def list_workspaces(self) -> list[dict]:
        return self.client.list_workspaces()

    def find_workspace(self, display_name: str) -> dict | None:
        return self.client.find_workspace_by_name(display_name)

    def ensure_workspace(
        self,
        display_name: str,
        *,
        description: str | None = None,
        capacity_id: str | None = None,
    ) -> dict:
        """Idempotently provision a workspace.

        If a workspace with ``display_name`` already exists, returns it as-is.
        Otherwise creates one — when ``capacity_id`` is provided the workspace
        is created directly on that capacity.

        Note: if the workspace exists but is on a different capacity than the
        one requested, this method does NOT reassign — call ``assign_capacity``
        explicitly to avoid surprising the caller.
        """
        existing = self.find_workspace(display_name)
        if existing is not None:
            return existing
        return self.client.create_workspace(
            display_name,
            description=description,
            capacity_id=capacity_id,
        )

    def delete_workspace(self, workspace_id: str) -> bool:
        return self.client.delete_workspace(workspace_id)

    def assign_capacity(self, workspace_id: str, capacity_id: str) -> bool:
        return self.client.assign_capacity(workspace_id, capacity_id)

    def list_capacities(self) -> list[dict]:
        return self.client.list_capacities()

    # -- Role assignments -----------------------------------------------------

    def members(self, workspace_id: str) -> list[dict]:
        return self.client.list_role_assignments(workspace_id)

    def add_user(
        self,
        workspace_id: str,
        *,
        object_id: str,
        role: Role = "Member",
    ) -> dict:
        """Grant a user a role on a workspace.

        ``object_id`` is the Azure AD object id of the user. Email→object_id
        resolution is intentionally out of scope here (requires Graph API);
        callers who only have an email resolve it upstream.
        """
        return self.client.add_role_assignment(
            workspace_id,
            principal_id=object_id,
            principal_type="User",
            role=role,
        )

    def add_service_principal(
        self,
        workspace_id: str,
        *,
        app_id: str,
        role: Role = "Contributor",
    ) -> dict:
        return self.client.add_role_assignment(
            workspace_id,
            principal_id=app_id,
            principal_type="ServicePrincipal",
            role=role,
        )

    def add_group(
        self,
        workspace_id: str,
        *,
        group_id: str,
        role: Role = "Member",
    ) -> dict:
        return self.client.add_role_assignment(
            workspace_id,
            principal_id=group_id,
            principal_type="Group",
            role=role,
        )

    def remove_assignment(self, workspace_id: str, role_assignment_id: str) -> bool:
        return self.client.delete_role_assignment(workspace_id, role_assignment_id)
