"""Fabric connector for ade-ops.

Handles Microsoft Fabric REST API interactions for Power BI items
(Reports, SemanticModels) and Fabric items (Notebooks, Pipelines).

Authentication strategies (in order of precedence):
1. Service Principal (client_id + client_secret + tenant_id) — best for CI.
2. Azure CLI (``az account get-access-token``) — best for local dev.
3. Device code (MSAL public client) — interactive fallback.

The strategy is chosen from credentials.yaml ``fabric.auth_method`` or auto-detected
when the field is missing.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from typing import Callable

import httpx


FABRIC_API_BASE = "https://api.fabric.microsoft.com/v1"
FABRIC_RESOURCE = "https://api.fabric.microsoft.com"

# Power BI data-plane audience — required for executeQueries (DAX) and
# other api.powerbi.com endpoints. Distinct from the Fabric API audience.
PBI_DATAPLANE_RESOURCE = "https://analysis.windows.net/powerbi/api"
PBI_API_BASE = "https://api.powerbi.com/v1.0/myorg"

# Long-running operation polling (getDefinition / updateDefinition).
LRO_MAX_ATTEMPTS = 20
LRO_INITIAL_WAIT = 2.0
LRO_MAX_WAIT = 10.0

# NOTE on the `format` query parameter of getDefinition:
# `format` is NOT a hint, it is a conversion request. Omitting it makes Fabric
# serve the item in its native storage format (PBIR or PBIR-Legacy for
# reports; TMDL or TMSL for semantic models). Passing `format=X` asks Fabric
# to convert from native to X — and if the conversion path is unsupported
# (typical case: PBIR-Legacy storage → PBIR conversion), Fabric returns
# 4xx + errorCode=Report_Report_FailedToExportReport with isRetriable=false.
#
# Therefore: for pull discovery we never pass `format`. The caller can still
# request an explicit conversion for normalisation use cases by threading the
# `format=` kwarg through `_fetch_definition_with_fallback`. See PBI-senior
# 2026-05-20 strategy memo and core/docs/fabric_404_vs_403.md.


def _fabric_error_code(response: httpx.Response) -> str | None:
    """Best-effort extraction of the `errorCode` field from a Fabric error body.

    Returns None if the response body is not JSON or carries no errorCode.
    """
    try:
        body = response.json()
    except (ValueError, TypeError):
        return None
    if not isinstance(body, dict):
        return None
    code = body.get("errorCode")
    return code if isinstance(code, str) else None

# Azure PowerShell client id — a public, multi-tenant app id that supports
# both device-code and ROPC flows for Microsoft APIs.
AZURE_PS_CLIENT_ID = "1950a258-227b-4e31-a9cf-717495945fc2"


# =============================================================================
# Authentication
# =============================================================================

class FabricAuthenticator:
    """Acquires and caches a Fabric API bearer token."""

    def __init__(self, auth_config: dict):
        """
        Args:
            auth_config: merged auth config (``fabric`` section of credentials.yaml,
                optionally overridden by ``project.yaml`` ``environments.{env}.platforms.{platform}.auth``).
                Recognised keys:
                    ``auth_method`` — ``service_principal`` | ``az_cli`` | ``device_code``
                    ``tenant_id``   — used by ``service_principal`` and ``device_code``
                    ``client_id``, ``client_secret`` — used by ``service_principal``
                    ``azure_config_dir`` — used by ``az_cli`` to select an Azure CLI profile
                    ``az_tenant_id``     — used by ``az_cli`` for ``--tenant`` (distinct from
                                            ``tenant_id`` so dual-identity setups can pin the
                                            Fabric tenant on az_cli without affecting
                                            service_principal/device_code flows)
        """
        self.config = auth_config or {}
        self.method = self.config.get("auth_method") or self._auto_detect_method()
        # Per-resource token cache. Keyed by the resource/audience URI so the same
        # authenticator instance can serve both the Fabric API and the PBI data-plane
        # without cross-contaminating cached tokens.
        self._token_cache: dict[str, str] = {}

    def _auto_detect_method(self) -> str:
        if all(self.config.get(k) for k in ("client_id", "client_secret", "tenant_id")):
            return "service_principal"
        if _az_cli_available():
            return "az_cli"
        return "device_code"

    def get_token(self, *, resource: str | None = None, force_refresh: bool = False) -> str:
        """Return a valid bearer token for ``resource``, fetching one if needed.

        Args:
            resource: target audience URI (e.g. ``PBI_DATAPLANE_RESOURCE`` for
                DAX queries). Defaults to ``FABRIC_RESOURCE`` (Fabric REST API).
            force_refresh: bypass the per-resource cache (use after a 401).
        """
        target = resource or FABRIC_RESOURCE
        if target in self._token_cache and not force_refresh:
            return self._token_cache[target]
        if self.method == "service_principal":
            token = self._get_token_sp(target)
        elif self.method == "az_cli":
            token = self._get_token_az_cli(target)
        elif self.method == "device_code":
            token = self._get_token_device_code(target)
        else:
            raise ValueError(
                f"Unknown fabric auth_method: {self.method!r}. "
                f"Expected one of: service_principal, az_cli, device_code."
            )
        self._token_cache[target] = token
        return token

    def _get_token_sp(self, resource: str) -> str:
        client_id = self.config.get("client_id")
        client_secret = self.config.get("client_secret")
        tenant_id = self.config.get("tenant_id")
        if not (client_id and client_secret and tenant_id):
            raise ValueError(
                "service_principal auth requires client_id, client_secret, tenant_id "
                "in credentials.yaml fabric section."
            )
        import msal  # lazy import — msal is optional unless this path is used
        app = msal.ConfidentialClientApplication(
            client_id=client_id,
            client_credential=client_secret,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
        )
        result = app.acquire_token_for_client(scopes=[f"{resource}/.default"])
        token = result.get("access_token")
        if not token:
            error = result.get("error_description") or result.get("error") or "unknown"
            raise RuntimeError(f"Fabric SP auth failed: {error}")
        return token

    def _get_token_az_cli(self, resource: str) -> str:
        az_path = _resolve_az_executable()
        if az_path is None:
            raise RuntimeError(
                "az CLI not found on PATH. Install Azure CLI or use auth_method=service_principal."
            )
        args = [az_path, "account", "get-access-token", "--resource", resource]

        az_tenant = self.config.get("az_tenant_id")
        if az_tenant:
            args.extend(["--tenant", az_tenant])

        # Optional per-call AZURE_CONFIG_DIR override. Lets the same machine
        # carry multiple az CLI profiles (e.g. native client-tenant user vs
        # guest identity) and route each Fabric call to the right identity
        # without the user exporting env vars by hand.
        env = None
        azure_config_dir = self.config.get("azure_config_dir")
        if azure_config_dir:
            env = {**os.environ, "AZURE_CONFIG_DIR": azure_config_dir}

        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
                env=env,
            )
        except subprocess.CalledProcessError as e:
            hint = f" (AZURE_CONFIG_DIR={azure_config_dir})" if azure_config_dir else ""
            tenant_hint = f" --tenant {az_tenant}" if az_tenant else ""
            raise RuntimeError(
                f"az account get-access-token failed{hint}: {e.stderr.strip()}\n"
                f"  Setup tip: az login{tenant_hint} --allow-no-subscriptions\n"
                f"  (the --allow-no-subscriptions flag is required for identities\n"
                f"  without an active Azure subscription on the target tenant — "
                f"common for guest users that only need Power BI / Fabric access)."
            ) from e
        token_data = json.loads(proc.stdout)
        return token_data["accessToken"]

    def _get_token_device_code(self, resource: str) -> str:
        tenant_id = self.config.get("tenant_id") or "common"
        import msal  # lazy import
        app = msal.PublicClientApplication(
            client_id=AZURE_PS_CLIENT_ID,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
        )
        flow = app.initiate_device_flow(scopes=[f"{resource}/.default"])
        if "user_code" not in flow:
            error = flow.get("error_description") or "device flow init failed"
            raise RuntimeError(f"Fabric device-code auth failed: {error}")
        print(flow["message"], flush=True)
        result = app.acquire_token_by_device_flow(flow)
        token = result.get("access_token")
        if not token:
            error = result.get("error_description") or result.get("error") or "unknown"
            raise RuntimeError(f"Fabric device-code auth failed: {error}")
        return token


def _resolve_az_executable() -> str | None:
    """Return the full path to the Azure CLI executable, or None if absent.

    On Windows ``az`` is actually ``az.cmd``; ``subprocess.run(['az', ...])``
    without ``shell=True`` does not honour ``PATHEXT`` and fails with
    ``FileNotFoundError`` even when ``az`` is on PATH. ``shutil.which`` does
    honour ``PATHEXT``, so it returns the resolved ``az.cmd`` path. On POSIX
    it returns the plain ``az`` path.
    """
    return shutil.which("az")


def _az_cli_available() -> bool:
    if _resolve_az_executable() is None:
        return False
    try:
        proc = subprocess.run(
            [_resolve_az_executable(), "--version"],
            capture_output=True, text=True, timeout=5,
        )
        return proc.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


# =============================================================================
# REST client
# =============================================================================

class FabricClient:
    """Fabric REST API client (workspace items: read + write)."""

    def __init__(self, token_provider: Callable[[], str]):
        self._token_provider = token_provider
        # F12 fix (2026-05-24): granular timeouts. The previous scalar
        # 60s applied to the entire transaction, killing legitimate large
        # uploads (e.g. 320 MB SemanticModel push) well before the server
        # finished receiving the body. Now: connect fail-fast (10s), large
        # read/write budgets (10 min) for big payloads + LRO polling.
        # Override via env var ADEOPS_HTTPX_READ_TIMEOUT (seconds, float).
        read_timeout = float(os.environ.get("ADEOPS_HTTPX_READ_TIMEOUT", "600"))
        self._client = httpx.Client(
            base_url=FABRIC_API_BASE,
            timeout=httpx.Timeout(
                connect=10.0,
                read=read_timeout,
                write=read_timeout,
                pool=10.0,
            ),
        )

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token_provider()}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Issue a request with one-shot token refresh on 401."""
        kwargs["headers"] = {**self._headers(), **kwargs.get("headers", {})}
        resp = self._client.request(method, url, **kwargs)
        if resp.status_code == 401:
            # token may have expired — refresh and retry once
            self._token_provider_refresh()
            kwargs["headers"] = {**self._headers(), **kwargs.get("headers", {})}
            resp = self._client.request(method, url, **kwargs)
        return resp

    def _token_provider_refresh(self) -> None:
        if hasattr(self._token_provider, "__self__") and isinstance(
            self._token_provider.__self__, FabricAuthenticator
        ):
            self._token_provider.__self__.get_token(force_refresh=True)

    def _poll_lro(self, location: str) -> httpx.Response:
        """Poll a long-running operation until completion or timeout.

        Fabric's ``getDefinition`` and ``updateDefinition`` return 202 Accepted
        with a ``Location`` header pointing to an operation resource. The
        terminal state is reported either as a 200 OK with the resource body or
        as an operation status payload with ``status`` == ``Succeeded`` /
        ``Failed``. For getDefinition the result is fetched from a separate
        ``/result`` endpoint.
        """
        wait = LRO_INITIAL_WAIT
        for _ in range(LRO_MAX_ATTEMPTS):
            time.sleep(wait)
            resp = self._request("GET", location)
            if resp.status_code == 202:
                wait = min(wait * 1.5, LRO_MAX_WAIT)
                continue
            if resp.status_code != 200:
                return resp
            # 200 — could be the final body or an operation-status envelope.
            try:
                body = resp.json()
            except ValueError:
                return resp
            status = body.get("status")
            if status in (None, "Succeeded"):
                return resp
            if status == "Failed":
                return resp
            # Still running — keep polling.
            wait = min(wait * 1.5, LRO_MAX_WAIT)
        raise TimeoutError(
            f"Fabric LRO timed out after {LRO_MAX_ATTEMPTS} polls of {location!r}"
        )

    def list_workspaces(self) -> list[dict]:
        resp = self._request("GET", "/workspaces")
        resp.raise_for_status()
        return resp.json().get("value", [])

    def get_workspace(self, workspace_id: str) -> dict:
        resp = self._request("GET", f"/workspaces/{workspace_id}")
        resp.raise_for_status()
        return resp.json()

    def find_workspace_by_name(self, display_name: str) -> dict | None:
        """Return the first workspace visible to the caller whose displayName matches."""
        for ws in self.list_workspaces():
            if ws.get("displayName") == display_name:
                return ws
        return None

    def create_workspace(
        self,
        display_name: str,
        *,
        description: str | None = None,
        capacity_id: str | None = None,
    ) -> dict:
        """Create a Fabric workspace.

        When ``capacity_id`` is provided it is sent in the create body so the
        workspace lands directly on that capacity. If the caller prefers a
        two-step provision flow, omit it and call ``assign_capacity`` after.
        """
        body: dict = {"displayName": display_name}
        if description is not None:
            body["description"] = description
        if capacity_id is not None:
            body["capacityId"] = capacity_id
        resp = self._request("POST", "/workspaces", json=body)
        resp.raise_for_status()
        return resp.json()

    def delete_workspace(self, workspace_id: str) -> bool:
        resp = self._request("DELETE", f"/workspaces/{workspace_id}")
        return resp.status_code in (200, 204)

    def list_capacities(self) -> list[dict]:
        resp = self._request("GET", "/capacities")
        resp.raise_for_status()
        return resp.json().get("value", [])

    def assign_capacity(self, workspace_id: str, capacity_id: str) -> bool:
        """Assign an existing workspace to a Fabric capacity.

        Fabric returns 202 Accepted with a Location header; the call polls
        to terminal state and returns True only on Succeeded.
        """
        resp = self._request(
            "POST",
            f"/workspaces/{workspace_id}/assignToCapacity",
            json={"capacityId": capacity_id},
        )
        if resp.status_code in (200, 204):
            return True
        if resp.status_code != 202:
            return False
        location = resp.headers.get("Location")
        if not location:
            return True
        poll_resp = self._poll_lro(location)
        if poll_resp.status_code != 200:
            return False
        try:
            body = poll_resp.json()
        except ValueError:
            return True
        return body.get("status") in (None, "Succeeded")

    def list_role_assignments(self, workspace_id: str) -> list[dict]:
        resp = self._request("GET", f"/workspaces/{workspace_id}/roleAssignments")
        resp.raise_for_status()
        return resp.json().get("value", [])

    def add_role_assignment(
        self,
        workspace_id: str,
        *,
        principal_id: str,
        principal_type: str,
        role: str,
    ) -> dict:
        """Grant a principal a role on a workspace.

        ``principal_type``: ``User`` | ``Group`` | ``ServicePrincipal``.
        ``role``: ``Admin`` | ``Member`` | ``Contributor`` | ``Viewer``.
        ``principal_id`` is the Azure AD object id (not the user email — for
        email-based lookup the caller resolves to object id via Graph first).
        """
        body = {
            "principal": {"id": principal_id, "type": principal_type},
            "role": role,
        }
        resp = self._request(
            "POST",
            f"/workspaces/{workspace_id}/roleAssignments",
            json=body,
        )
        resp.raise_for_status()
        return resp.json()

    def delete_role_assignment(self, workspace_id: str, role_assignment_id: str) -> bool:
        resp = self._request(
            "DELETE",
            f"/workspaces/{workspace_id}/roleAssignments/{role_assignment_id}",
        )
        return resp.status_code in (200, 204)

    def list_items(self, workspace_id: str, item_type: str | None = None) -> list[dict]:
        params = {"type": item_type} if item_type else {}
        resp = self._request("GET", f"/workspaces/{workspace_id}/items", params=params)
        resp.raise_for_status()
        return resp.json().get("value", [])

    def find_item_by_name(
        self,
        workspace_id: str,
        item_type: str,
        display_name: str,
    ) -> dict | None:
        """Return the first item in the workspace whose displayName matches.

        Used to resolve the target item ID at push time, supporting both
        same-env round-trips and cross-env promote where the local folder
        name + overlay suffix point to a different item id per environment.
        """
        for item in self.list_items(workspace_id, item_type=item_type):
            if item.get("displayName") == display_name:
                return item
        return None

    def get_item(self, workspace_id: str, item_id: str) -> dict:
        resp = self._request("GET", f"/workspaces/{workspace_id}/items/{item_id}")
        resp.raise_for_status()
        return resp.json()

    def get_item_definition(
        self, workspace_id: str, item_id: str, *, format: str | None = None,
    ) -> dict:
        """Get the item definition (parts) as the Fabric API returns it.

        The result has shape ``{"definition": {"parts": [{"path": ..., "payload": ...,
        "payloadType": "InlineBase64"}, ...]}}``.

        Handles 202 Accepted by polling the operation's ``Location`` header and
        then fetching ``/result``. Pass ``format`` to request a specific layout
        (e.g. ``PBIR`` for Report, ``TMDL`` for SemanticModel).
        """
        params = {"format": format} if format else {}
        resp = self._request(
            "POST",
            f"/workspaces/{workspace_id}/items/{item_id}/getDefinition",
            params=params,
        )

        if resp.status_code == 202:
            location = resp.headers.get("Location")
            if not location:
                raise RuntimeError(
                    "Fabric getDefinition returned 202 without a Location header."
                )
            poll_resp = self._poll_lro(location)
            poll_resp.raise_for_status()
            body = poll_resp.json() if poll_resp.content else {}
            # Operation succeeded — fetch the result payload separately.
            if body.get("status") == "Succeeded" or "definition" not in body:
                result_url = location.rstrip("/") + "/result"
                result_resp = self._request("GET", result_url)
                result_resp.raise_for_status()
                return result_resp.json()
            return body

        resp.raise_for_status()
        return resp.json()

    def update_item_definition(
        self,
        workspace_id: str,
        item_id: str,
        definition: dict,
    ) -> bool:
        """Replace an item's definition.

        Returns True only when the operation reaches a terminal Succeeded
        state. 202 responses are polled to completion. On failure the Fabric
        error body (HTTP status + LRO ``errorCode`` / ``message``) is printed
        so the caller does not have to monkey-patch the connector to see why
        a push failed (F14 fix, 2026-05-24).
        """
        resp = self._request(
            "POST",
            f"/workspaces/{workspace_id}/items/{item_id}/updateDefinition",
            json={"definition": definition},
        )
        if resp.status_code == 200:
            return True
        if resp.status_code != 202:
            print(
                f"  [ERROR] updateDefinition HTTP {resp.status_code}: "
                f"{resp.text[:500]}"
            )
            return False
        location = resp.headers.get("Location")
        if not location:
            # No location to poll — best-effort treat as accepted.
            return True
        poll_resp = self._poll_lro(location)
        if poll_resp.status_code != 200:
            print(
                f"  [ERROR] updateDefinition LRO poll HTTP "
                f"{poll_resp.status_code}: {poll_resp.text[:500]}"
            )
            return False
        try:
            body = poll_resp.json()
        except ValueError:
            return True  # 200 with empty body — accepted.
        status = body.get("status")
        if status and status != "Succeeded":
            err = body.get("error") or {}
            print(
                f"  [ERROR] updateDefinition LRO status={status} "
                f"errorCode={err.get('errorCode')!r} "
                f"message={err.get('message')!r}"
            )
            return False
        return True

    def create_item(
        self,
        workspace_id: str,
        *,
        display_name: str,
        item_type: str,
        definition: dict | None = None,
    ) -> dict:
        """Create an item. Handles 202 Accepted LRO (Notebook, Pipeline, etc.).

        Fabric returns 201 Created synchronously for some item types and 202
        with a Location header for others (notably Notebook + DataPipeline,
        where item provisioning happens asynchronously). On 202 we poll to
        terminal state and fetch the result.
        """
        body: dict = {"displayName": display_name, "type": item_type}
        if definition is not None:
            body["definition"] = definition
        resp = self._request("POST", f"/workspaces/{workspace_id}/items", json=body)

        if resp.status_code == 202:
            location = resp.headers.get("Location")
            if not location:
                raise RuntimeError(
                    "Fabric create_item returned 202 without a Location header."
                )
            poll_resp = self._poll_lro(location)
            poll_resp.raise_for_status()
            body_payload = poll_resp.json() if poll_resp.content else {}
            # If the poll body is an operation envelope, fetch the result.
            if body_payload.get("status") == "Succeeded" or "id" not in body_payload:
                result_url = location.rstrip("/") + "/result"
                result_resp = self._request("GET", result_url)
                result_resp.raise_for_status()
                return result_resp.json()
            return body_payload

        resp.raise_for_status()
        return resp.json()


# =============================================================================
# ade-ops connector
# =============================================================================

# Item types we currently sync. Extend as more Fabric scopes come online.
_DEFAULT_ITEM_TYPES = ("Report", "SemanticModel")


class FabricConnector:
    """ade-ops connector for Microsoft Fabric workspaces.

    Implements ``PlatformConnector``. The ``remote_path`` carried through the
    engine has the form ``{workspace_id}|{item_id}|{item_type}`` — the engine
    does not interpret it, only round-trips it back to ``pull_object``.
    """

    def __init__(self, authenticator: FabricAuthenticator):
        self.auth = authenticator
        self.client = FabricClient(self.auth.get_token)

    @classmethod
    def from_credentials(
        cls,
        credentials: dict,
        *,
        env_platform_auth: dict | None = None,
    ) -> FabricConnector:
        """Build a connector, optionally overriding auth from project.yaml.

        Args:
            credentials: loaded ``credentials.yaml``.
            env_platform_auth: ``environments.{env}.platforms.fabric.auth``
                block from ``project.yaml`` (or ``None`` if not set). When
                present, its keys override the ones in ``credentials.fabric``,
                making it possible to use a different Azure identity per
                environment and per platform without editing credentials.
        """
        fabric = credentials.get("fabric") or {}
        merged = dict(fabric)
        if env_platform_auth:
            override = dict(env_platform_auth)
            # Normalize: project.yaml block uses `method`; credentials uses
            # `auth_method`. Internally we only carry `auth_method`.
            if "method" in override and "auth_method" not in override:
                override["auth_method"] = override.pop("method")
            merged.update({k: v for k, v in override.items() if v is not None})
        if not merged:
            raise ValueError(
                "No fabric auth config found. Provide either credentials.yaml "
                "fabric section or environments.{env}.platforms.fabric.auth "
                "in project.yaml."
            )
        return cls(FabricAuthenticator(merged))

    def list_objects(
        self,
        env_config: dict,
        overlay: dict,
        *,
        pipeline_filter: str | None = None,
    ) -> list[dict]:
        """List Power BI / Fabric items across the workspaces configured for the env."""
        workspace_ids = _resolve_workspace_ids(env_config, overlay)
        if not workspace_ids:
            raise ValueError(
                "No workspace_id found for the fabric scope. Set "
                "environments.{env}.platforms.fabric.workspace_id or overlay "
                "fabric.{model,report}_workspace_id."
            )

        item_types = overlay.get("fabric", {}).get("item_types") or _DEFAULT_ITEM_TYPES

        result: list[dict] = []
        by_ws_type: dict[tuple[str, str], list[dict]] = {}
        for ws_id in workspace_ids:
            for item_type in item_types:
                items = self.client.list_items(ws_id, item_type=item_type)
                by_ws_type[(ws_id, item_type)] = items
                for item in items:
                    if pipeline_filter and pipeline_filter not in item.get("displayName", ""):
                        continue
                    result.append(self._to_object_entry(item, ws_id))

        overlay_warnings = _check_overlay_targets(overlay, by_ws_type)
        for msg in overlay_warnings:
            print(f"  [WARN] {msg}")
        if overlay_warnings and os.environ.get("ADEOPS_STRICT_OVERLAY"):
            raise ValueError(
                "Overlay validation failed (ADEOPS_STRICT_OVERLAY=1); see warnings above."
            )
        return result

    def pull_object(self, remote_path: str) -> dict[str, bytes] | None:
        """Download an item's definition and return its parts as a folder dict.

        Uses Fabric's native storage format (no ``format`` query parameter,
        see module-level NOTE on getDefinition). This covers both PBIR and
        PBIR-Legacy reports, and TMDL/TMSL semantic models, in one call —
        no conversion attempt, no spurious 404s from unsupported conversion
        paths. The actual format returned is recorded in the ``.fabric.json``
        sidecar (``"format": "native"``) so future tooling can branch on it.

        Keys are relative paths (forward slashes); the engine writes them
        under ``state/{env}/{scope}/{local_path}/``.
        """
        try:
            workspace_id, item_id, item_type = _parse_remote_path(remote_path)
        except ValueError:
            return None

        payload, fmt_used = self._fetch_definition_with_fallback(
            workspace_id, item_id, item_type, preferred_format=None,
        )
        if payload is None:
            return None

        parts = (payload.get("definition") or {}).get("parts") or []
        files: dict[str, bytes] = {}
        for part in parts:
            path = part.get("path")
            payload_b64 = part.get("payload")
            if not path or payload_b64 is None:
                continue
            try:
                files[path] = base64.b64decode(payload_b64)
            except (binascii.Error, ValueError):
                return None

        # Persist the remote-path metadata alongside the parts so push can
        # round-trip workspace+item+type without depending on state.yaml.
        files[".fabric.json"] = json.dumps(
            {
                "workspace_id": workspace_id,
                "item_id": item_id,
                "item_type": item_type,
                "format": fmt_used,
            },
            indent=2,
            sort_keys=True,
        ).encode("utf-8")

        return files

    def materialize_siblings(
        self,
        folder_name: str,
        files: dict[str, bytes],
    ) -> dict[str, bytes]:
        """Emit files that should sit alongside a pulled item folder.

        Two cases handled today:

        - ``<base>.Report`` → emits ``<base>.pbip`` so Power BI Desktop can
          open the folder directly.
        - ``<base>.SemanticModel`` → emits a local-only editor stub:
          ``<base>_editor.pbip`` + ``<base>_editor.Report/`` (minimal Report
          with ``definition.pbir`` byPath-bound to the sibling
          SemanticModel). Opening ``<base>_editor.pbip`` in Power BI Desktop
          loads the model so you can edit measures/relationships in Model
          View without depending on a real companion report. The stub is
          local-only: the connector skips it on push (see ``group_files``).

        Other item types return no siblings.

        Args:
            folder_name: leaf name of the pulled folder (e.g.
                ``"rfq_qa.Report"`` or ``"ssp_qa.SemanticModel"``).
            files: contents of the folder, keyed by relative path. Reserved
                for future use (e.g. inspecting ``.fabric.json`` to branch
                on format) — unused today.

        Returns:
            Dict of ``{path: bytes}``. Keys are paths relative to the
            parent of the pulled folder (forward slashes allowed for
            nested files inside the editor stub).
        """
        del files
        if folder_name.endswith(".Report"):
            base = folder_name[: -len(".Report")]
            pbip = {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
                "version": "1.0",
                "artifacts": [{"report": {"path": folder_name}}],
                "settings": {"enableAutoRecovery": True},
            }
            return {
                f"{base}.pbip": json.dumps(pbip, indent=2).encode("utf-8"),
            }
        if folder_name.endswith(".SemanticModel"):
            base = folder_name[: -len(".SemanticModel")]
            editor_folder = f"{base}_editor.Report"
            pbip = {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
                "version": "1.0",
                "artifacts": [{"report": {"path": editor_folder}}],
                "settings": {"enableAutoRecovery": True},
            }
            pbir = {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
                "version": "4.0",
                "datasetReference": {
                    "byPath": {"path": f"../{folder_name}"},
                },
            }
            platform = {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
                "metadata": {
                    "type": "Report",
                    "displayName": f"{base}_editor",
                },
                "config": {
                    "version": "2.0",
                    "logicalId": "00000000-0000-0000-0000-000000000000",
                },
            }
            version_meta = {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json",
                "version": "2.0.0",
            }
            report_def = {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/3.2.0/schema.json",
                "themeCollection": {
                    "baseTheme": {
                        "name": "CY25SU12",
                        "reportVersionAtImport": {
                            "visual": "2.5.0",
                            "report": "3.1.0",
                            "page": "2.3.0",
                        },
                        "type": "SharedResources",
                    },
                },
                "resourcePackages": [
                    {
                        "name": "SharedResources",
                        "type": "SharedResources",
                        "items": [
                            {
                                "name": "CY25SU12",
                                "path": "BaseThemes/CY25SU12.json",
                                "type": "BaseTheme",
                            },
                        ],
                    },
                ],
                "settings": {},
            }
            # Power BI Desktop rejects a Report with zero pages
            # ("Definition contains no pages"). Ship an empty Model View
            # page so the stub opens cleanly — the user comes here to edit
            # the model, not the page, so a blank canvas is the right UX.
            page_id = "modelview01modelview"  # 20-char alphanumeric (PBIR convention)
            pages_meta = {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.0.0/schema.json",
                "pageOrder": [page_id],
                "activePageName": page_id,
            }
            page_def = {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json",
                "name": page_id,
                "displayName": "Model View",
                "displayOption": "FitToPage",
                "height": 720,
                "width": 1280,
            }
            return {
                f"{base}_editor.pbip": json.dumps(pbip, indent=2).encode("utf-8"),
                f"{editor_folder}/.platform": json.dumps(platform, indent=2).encode("utf-8"),
                f"{editor_folder}/definition.pbir": json.dumps(pbir, indent=2).encode("utf-8"),
                f"{editor_folder}/definition/version.json": json.dumps(version_meta, indent=2).encode("utf-8"),
                f"{editor_folder}/definition/report.json": json.dumps(report_def, indent=2).encode("utf-8"),
                f"{editor_folder}/definition/pages/pages.json": json.dumps(pages_meta, indent=2).encode("utf-8"),
                f"{editor_folder}/definition/pages/{page_id}/page.json": json.dumps(page_def, indent=2).encode("utf-8"),
            }
        return {}

    def _fetch_definition_with_fallback(
        self,
        workspace_id: str,
        item_id: str,
        item_type: str,
        preferred_format: str | None = None,
    ) -> tuple[dict | None, str | None]:
        """Fetch item definition, preferring Fabric's native storage format.

        Default behaviour (``preferred_format=None``) omits the ``format``
        query parameter so Fabric serves the item in whatever PBIR / TMDL
        flavour it stores natively. This handles ~90% of cases including
        PBIR-Legacy reports born from the pre-2024 "Publish to Power BI"
        ``.pbix`` flow — no explicit retry needed and no spurious 404 from
        a conversion request.

        Passing a non-None ``preferred_format`` ("PBIR" / "TMDL" / ...) asks
        Fabric to convert from native to that format. If the conversion path
        is unsupported, the call fails with
        ``errorCode=Report_Report_FailedToExportReport`` (isRetriable=false)
        and no retry is attempted — by design, since the conversion was a
        deliberate choice. Use only for normalisation use cases.

        Returns ``(payload, format_used)`` where ``format_used`` is the
        requested string or ``"native"`` when none was passed. Returns
        ``(None, None)`` on any failure; the diagnostic is printed to stdout
        so the caller's per-item summary stays root-cause-able.
        """
        fmt_label = preferred_format or "native"
        try:
            payload = self.client.get_item_definition(
                workspace_id, item_id, format=preferred_format,
            )
            return payload, fmt_label
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            body_err = _fabric_error_code(e.response)

            if body_err == "Report_Report_FailedToExportReport":
                # Fabric refuses to serve this item in the requested form.
                # With the default native path this is rare — typically the
                # report's backing model is Premium Files / Direct Lake
                # which blocks definition export, or the artefact is in a
                # corrupt state. With an explicit preferred_format this
                # usually means the conversion path itself is unsupported
                # (e.g. PBIR-Legacy storage → PBIR conversion).
                print(
                    f"  [ERROR] {item_type} {item_id}: Fabric cannot serve\n"
                    f"          the definition (errorCode={body_err},\n"
                    f"          isRetriable=false, requested format={fmt_label}).\n"
                    f"          Likely cause: backing model is Direct Lake /\n"
                    f"          Premium Files (definition export blocked) or\n"
                    f"          the item is corrupt.\n"
                    f"          Recovery for migration: definition is usually\n"
                    f"          not required when the target model is being\n"
                    f"          rebuilt. If a binary archive is required, use\n"
                    f"          the PBI legacy Export API\n"
                    f"          (GET api.powerbi.com/v1.0/myorg/groups/{workspace_id}\n"
                    f"          /reports/{item_id}/Export) — tracked as the\n"
                    f"          `legacy-import` CLI in the backlog."
                )
                return None, None

            if status == 404 and not body_err:
                # Nude 404 EntityNotFound — auth trap. The caller can list
                # the item but not read its definition; the common cause
                # is the calling UPN lacking PBI Pro on the workspace
                # (Fabric returns 404 instead of 403 — least-information
                # disclosure). See core/docs/fabric_404_vs_403.md.
                print(
                    f"  [WARN] {item_type} {item_id}: getDefinition returned\n"
                    f"         404 EntityNotFound with no further detail.\n"
                    f"         Most common cause: caller identity lacks Power\n"
                    f"         BI Pro on this workspace (Fabric returns 404\n"
                    f"         instead of 403 — least-information disclosure).\n"
                    f"         Verify with `az account show`; PBI Pro is on\n"
                    f"         the UPN, not on the workspace."
                )
                return None, None

            # Other HTTP errors — log status + errorCode so the per-item
            # signal makes it into the caller's summary.
            print(
                f"  [ERROR] {item_type} {item_id}: getDefinition failed\n"
                f"          status={status} errorCode={body_err or 'unknown'}"
            )
            return None, None
        except TimeoutError:
            print(
                f"  [ERROR] {item_type} {item_id}: getDefinition timed out"
            )
            return None, None

    def group_files(
        self,
        files: dict[str, bytes],
    ) -> dict[str, dict[str, bytes]]:
        """Group flat file paths into per-item PBIP folders.

        Files under ``{ItemType}/{Name}.{ItemType}/...`` are bundled into one
        group keyed by ``{ItemType}/{Name}.{ItemType}``. Anything outside that
        layout is returned as a 1-file group keyed by its own path so the push
        loop can still iterate uniformly.
        """
        groups: dict[str, dict[str, bytes]] = {}
        for path, content in files.items():
            # .pbip files are Power BI Desktop project markers that live
            # next to the item folder. They are materialized locally by
            # pull → materialize_siblings; Fabric has no use for them, so
            # drop them here instead of trying to push a singleton file.
            if path.endswith(".pbip"):
                continue
            group, sub = _split_pbip_path(path)
            # *_editor.Report/ folders are local-only stubs materialized at
            # pull time so PBI Desktop can open a SemanticModel via byPath.
            # They are not real items in any workspace — never push them.
            if group is not None and group.endswith("_editor.Report"):
                continue
            if group is None:
                groups.setdefault(path, {})[""] = content
            else:
                groups.setdefault(group, {})[sub] = content
        return groups

    def push_object(
        self,
        local_path: str,
        content: bytes | dict[str, bytes],
        env_config: dict,
        overlay: dict,
    ) -> bool:
        """Upload a PBIP-style folder to Fabric, creating or updating in place.

        Routing rules:

        1. Target workspace_id is resolved from the overlay (``power_bi.report_workspace_id``
           for Reports, ``power_bi.model_workspace_id`` for SemanticModels),
           falling back to ``env_config.platforms.fabric.workspace_id``.
        2. Target display name = folder base name + overlay suffix
           (``power_bi.report_suffix`` for Reports, ``power_bi.model_suffix``
           for SemanticModels).
        3. The connector looks up the item in the target workspace by display
           name. If found → ``updateDefinition``. If not → ``create_item``.
        4. For Reports, ``definition.pbir`` is rewritten to a ``byConnection``
           reference pointing at ``overlay.power_bi.model_id``. This makes the
           same source folder deployable to any env without manual edits.

        The ``.fabric.json`` sidecar is informational only here — it carries
        provenance but is not consulted for target routing.
        """
        if not isinstance(content, dict):
            print(
                f"  [ERROR] FabricConnector requires a folder payload (got bytes for {local_path!r})."
            )
            return False

        item_type = _item_type_from_local_path(local_path)
        if item_type is None:
            print(
                f"  [ERROR] {local_path!r} is not a recognized PBIP folder "
                f"(expected suffix .Report or .SemanticModel)."
            )
            return False

        target_workspace = _resolve_target_workspace(item_type, env_config, overlay)
        if not target_workspace:
            print(
                f"  [ERROR] No target workspace for {item_type}. Set overlay "
                f"power_bi.{'report' if item_type == 'Report' else 'model'}_workspace_id "
                f"or env platforms.fabric.workspace_id."
            )
            return False

        target_name = _compute_target_display_name(local_path, item_type, overlay)
        model_id = (overlay.get("power_bi") or {}).get("model_id")

        # Rebind definition.pbir to byConnection if we're pushing a Report and
        # we have a target model_id. For PBIR-Legacy reports (no definition.pbir
        # in the parts), this is a no-op.
        rebound_content = dict(content)
        if item_type == "Report":
            if model_id:
                rebound_content = _rebind_pbir_to_connection(rebound_content, model_id)
            elif "definition.pbir" in rebound_content:
                print(
                    f"  [WARN] No power_bi.model_id in overlay — definition.pbir "
                    f"will be pushed without rebind. Cross-env promote will break."
                )

        parts = []
        for sub_path, blob in sorted(rebound_content.items()):
            if _should_exclude_from_push(sub_path):
                continue
            parts.append(
                {
                    "path": sub_path,
                    "payload": base64.b64encode(blob).decode("ascii"),
                    "payloadType": "InlineBase64",
                }
            )

        if not parts:
            return False

        try:
            existing = self.client.find_item_by_name(
                target_workspace, item_type, target_name,
            )
        except httpx.HTTPStatusError as e:
            print(f"  [ERROR] Failed to query target workspace: {e}")
            return False

        if existing is not None:
            print(f"  [PUSH] {item_type} {target_name!r} -> update {existing['id']}")
            return self.client.update_item_definition(
                target_workspace, existing["id"], {"parts": parts},
            )

        print(f"  [PUSH] {item_type} {target_name!r} -> create in {target_workspace}")
        try:
            created = self.client.create_item(
                target_workspace,
                display_name=target_name,
                item_type=item_type,
                definition={"parts": parts},
            )
            return bool(created.get("id"))
        except httpx.HTTPStatusError as e:
            print(f"  [ERROR] create_item failed: {e}")
            return False

    def preview_push(
        self,
        local_path: str,
        content: object,
        env_config: dict,
        overlay: dict,
    ) -> dict:
        """Resolve the push target without executing the upload.

        Returns a dict with the routing decision (F11 dry-run enrichment,
        2026-05-24):

        - ``item_type``: "Report" | "SemanticModel" | None
        - ``target_workspace_id``: str | None
        - ``target_display_name``: str | None
        - ``matched_existing_id``: str | None  (None means "would create new")
        - ``error``: str | None  (only set if routing cannot be resolved)

        The engine's dry-run loop uses this to print what would happen at
        push time, including the resolved target name and matched item id.
        Before this method existed, dry-run only printed the source folder
        name — operators could not verify routing before the real push.
        """
        result: dict[str, object | None] = {
            "item_type": None,
            "target_workspace_id": None,
            "target_display_name": None,
            "matched_existing_id": None,
            "error": None,
        }

        item_type = _item_type_from_local_path(local_path)
        if item_type is None:
            result["error"] = (
                f"{local_path!r} not a recognised PBIP folder "
                f"(expected .Report or .SemanticModel suffix)"
            )
            return result
        result["item_type"] = item_type

        target_workspace = _resolve_target_workspace(item_type, env_config, overlay)
        if not target_workspace:
            result["error"] = (
                f"No target workspace for {item_type}. Set overlay "
                f"power_bi.{'report' if item_type == 'Report' else 'model'}_workspace_id."
            )
            return result
        result["target_workspace_id"] = target_workspace

        target_name = _compute_target_display_name(local_path, item_type, overlay)
        result["target_display_name"] = target_name

        try:
            existing = self.client.find_item_by_name(
                target_workspace, item_type, target_name,
            )
            if existing is not None:
                result["matched_existing_id"] = existing.get("id")
        except Exception as e:
            result["error"] = f"find_item_by_name failed: {e}"

        return result

    def execute_dax(
        self,
        workspace_id: str,
        dataset_id: str,
        query: str,
    ) -> dict:
        """Execute a DAX query against a Power BI semantic model.

        Uses the Power BI data-plane audience
        (``https://analysis.windows.net/powerbi/api``), which is distinct from the
        Fabric REST API audience. The token is acquired and cached independently.

        Args:
            workspace_id: Fabric workspace id where the semantic model lives.
            dataset_id: Power BI dataset (semantic model) id.
            query: DAX expression (e.g. ``"EVALUATE TOPN(5, dm_supplier)"``).

        Returns:
            Dict with:
                ``columns`` — list of column names (``[Table].[Col]`` prefix stripped).
                ``rows``    — list of row dicts keyed by column name.

        Raises:
            RuntimeError: on HTTP / auth failure (with a human-readable message).
        """
        token = self.auth.get_token(resource=PBI_DATAPLANE_RESOURCE)
        url = f"{PBI_API_BASE}/groups/{workspace_id}/datasets/{dataset_id}/executeQueries"
        body = {
            "queries": [{"query": query}],
            "serializerSettings": {"includeNulls": True},
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        resp = httpx.post(url, json=body, headers=headers, timeout=60.0)
        if resp.status_code == 401:
            token = self.auth.get_token(resource=PBI_DATAPLANE_RESOURCE, force_refresh=True)
            headers["Authorization"] = f"Bearer {token}"
            resp = httpx.post(url, json=body, headers=headers, timeout=60.0)

        if not resp.is_success:
            _raise_dax_error(resp)

        data = resp.json()
        tables = ((data.get("results") or [{}])[0]).get("tables") or []
        if not tables:
            return {"columns": [], "rows": []}

        rows_raw = tables[0].get("rows") or []
        if not rows_raw:
            return {"columns": [], "rows": []}

        raw_keys = list(rows_raw[0].keys())
        columns = [_strip_pbi_col_prefix(k) for k in raw_keys]
        rows = [
            {_strip_pbi_col_prefix(k): v for k, v in row.items()}
            for row in rows_raw
        ]
        return {"columns": columns, "rows": rows}

    def get_hash(self, remote_path: str) -> str | None:
        files = self.pull_object(remote_path)
        if not files:
            return None
        hasher = hashlib.sha256()
        for path in sorted(files):
            hasher.update(path.encode("utf-8"))
            hasher.update(b"\0")
            hasher.update(files[path])
        return f"sha256:{hasher.hexdigest()[:16]}"

    @staticmethod
    def _to_object_entry(item: dict, workspace_id: str) -> dict:
        item_id = item["id"]
        item_type = item.get("type", "Item")
        display = item.get("displayName") or item_id
        safe_name = _safe_filename(display)
        # PBIP convention: a Report folder is ``{Name}.Report``, a model is
        # ``{Name}.SemanticModel``. Power BI Desktop opens these directly.
        # The folder suffix (.Report / .SemanticModel / .Lakehouse) already
        # encodes item type — no extra directory level needed. This keeps
        # state symmetric with src lay-out (#20 fabric-diff-path-symmetry).
        local_rel = f"{safe_name}.{item_type}"
        remote_path = f"{workspace_id}|{item_id}|{item_type}"
        return {
            "path": remote_path,
            "local_path": local_rel,
            "type": item_type.upper(),
            "modified": item.get("modifiedDate")
            or datetime.now(timezone.utc).isoformat(),
        }


# =============================================================================
# Helpers
# =============================================================================

def _strip_pbi_col_prefix(key: str) -> str:
    """Strip the ``[TableName].`` prefix from a Power BI executeQueries column key.

    The API returns row keys like ``[dm_supplier].[supplier_name]``. We surface
    only the column part (``supplier_name``) so the CLI output is readable.
    Plain keys without brackets (e.g. from ``EVALUATE ROW(...)``) are returned as-is.
    """
    if key.startswith("[") and "].[" in key:
        col_part = key.split("].[", 1)[1]
        return col_part.rstrip("]")
    return key


def _raise_dax_error(resp: httpx.Response) -> None:
    """Raise a RuntimeError with a human-readable message for a failed DAX call."""
    try:
        body = resp.json()
    except (ValueError, TypeError):
        raise RuntimeError(f"DAX query failed: HTTP {resp.status_code}")

    err = body.get("error") or {}
    code = err.get("code", "")
    msg = err.get("message", "")

    if resp.status_code == 403:
        raise RuntimeError(
            f"DAX query forbidden (HTTP 403).\n"
            f"  Verify the identity has access to the dataset (Viewer or above).\n"
            f"  If you see this on a guest identity, ensure the UPN has Power BI Pro.\n"
            f"  Error: {msg or code}"
        )

    if msg and ("type mismatch" in msg.lower() or "cannot convert" in msg.lower()):
        raise RuntimeError(
            f"DAX type error — {msg}\n"
            f"  Hint: string literals need double-quotes in DAX: "
            f'FILTER(T, [col] = "value").'
        )

    detail = f"{code} — {msg}" if msg else f"HTTP {resp.status_code}"
    raise RuntimeError(f"DAX query failed: {detail}")


def _check_overlay_targets(
    overlay: dict,
    by_ws_type: dict[tuple[str, str], list[dict]],
) -> list[str]:
    """Return diagnostic messages for overlay-declared items not found in their
    configured workspaces.

    Catches misconfiguration like ``power_bi.model_workspace_id`` pointing at a
    workspace that does not contain the configured ``model_id`` / ``model_name``
    — previously a silent skip during ``pull``. Set ``ADEOPS_STRICT_OVERLAY=1``
    to turn warnings into a hard failure.
    """
    pbi = overlay.get("power_bi") or {}
    msgs: list[str] = []

    model_ws = pbi.get("model_workspace_id") or (overlay.get("fabric") or {}).get("workspace_id")
    model_id = pbi.get("model_id")
    model_name = pbi.get("model_name")
    if model_ws and (model_id or model_name):
        in_ws = by_ws_type.get((model_ws, "SemanticModel"), [])
        match = any(
            (model_id and item.get("id") == model_id)
            or (model_name and item.get("displayName") == model_name)
            for item in in_ws
        )
        if not match:
            target = f"model_id={model_id}" if model_id else f"model_name={model_name}"
            seen = [item.get("id") for item in in_ws]
            msgs.append(
                f"overlay.power_bi.{target} NOT FOUND in model_workspace_id={model_ws}. "
                f"Workspace contains {len(in_ws)} SemanticModel(s): {seen}. "
                f"Verify overlay.power_bi.model_workspace_id — the model may live "
                f"in a different workspace."
            )
    return msgs


def _resolve_workspace_ids(env_config: dict, overlay: dict) -> list[str]:
    """Collect the workspace ids to operate on for this env.

    Priority:
        1. Overlay ``fabric.model_workspace_id`` + ``fabric.report_workspace_id``
           (deduplicated).
        2. ``environments.{env}.platforms.fabric.workspace_id`` from project.yaml.
    """
    ids: list[str] = []
    fabric_overlay = overlay.get("fabric", {}) or overlay.get("power_bi", {}) or {}
    for key in ("model_workspace_id", "report_workspace_id", "workspace_id"):
        value = fabric_overlay.get(key)
        if value and value not in ids:
            ids.append(value)

    fabric_env = env_config.get("platforms", {}).get("fabric", {})
    env_ws = fabric_env.get("workspace_id")
    if env_ws and env_ws not in ids:
        ids.append(env_ws)

    return ids


def _parse_remote_path(remote_path: str) -> tuple[str, str, str]:
    """Split ``{workspace_id}|{item_id}|{item_type}`` into its parts."""
    parts = remote_path.split("|")
    if len(parts) != 3:
        raise ValueError(f"Invalid fabric remote_path: {remote_path!r}")
    return parts[0], parts[1], parts[2]


_PBIP_SUFFIXES = (".Report", ".SemanticModel")


def _split_pbip_path(path: str) -> tuple[str | None, str]:
    """Split a flat file path into a PBIP group and the part beneath it.

    Returns ``(group, sub_path)`` where ``group`` is the ``{ItemType}/{Name}.{ItemType}``
    prefix and ``sub_path`` is the remainder. If the path isn't inside a PBIP
    folder, ``group`` is None.
    """
    parts = path.split("/")
    for i, segment in enumerate(parts):
        for suffix in _PBIP_SUFFIXES:
            if segment.endswith(suffix):
                group = "/".join(parts[: i + 1])
                sub = "/".join(parts[i + 1 :])
                return group, sub
    return None, path


def _item_type_from_local_path(local_path: str) -> str | None:
    """Recover the Fabric item type from a PBIP folder path's suffix.

    ``Report/Demo.Report`` → ``Report``.
    ``SemanticModel/project.SemanticModel`` → ``SemanticModel``.
    Anything else returns None.
    """
    last_segment = local_path.rstrip("/").split("/")[-1]
    for suffix in _PBIP_SUFFIXES:
        if last_segment.endswith(suffix):
            return suffix.lstrip(".")
    return None


# Well-known PBIP artifacts that are NOT part of the deployable definition.
# Shipping them inflates the payload, slows uploads, and can hit Fabric API
# size limits. F13 (2026-05-24): a 320 MB .pbi/cache.abf was 99% of a
# SemanticModel push payload — the cache is Analysis Services workspace
# metadata, regenerated by PBI Desktop on every refresh, never deployable.
#
# Exact-match exclusions (root-level marker files + sidecars).
_PUSH_EXCLUDE_EXACT: frozenset[str] = frozenset({
    "",
    ".fabric.json",
    ".platform",
    ".gitignore",
    "model.bim",  # legacy binary mirror — TMDL is authoritative
})

# Path-prefix exclusions (entire subtrees). `.pbi/` carries the Analysis
# Services workspace cache + local PBI Desktop settings; none of it is
# deployable.
_PUSH_EXCLUDE_PREFIX: tuple[str, ...] = (
    ".pbi/",
)


def _should_exclude_from_push(sub_path: str) -> bool:
    """Return True when a file path inside a PBIP folder should NOT ship."""
    if sub_path in _PUSH_EXCLUDE_EXACT:
        return True
    return any(sub_path.startswith(p) for p in _PUSH_EXCLUDE_PREFIX)


def _compute_target_display_name(
    local_path: str, item_type: str, overlay: dict,
) -> str:
    """Compute the target Fabric displayName for a push.

    Resolution priority (highest authority first — F11 fix 2026-05-24):

    1. **Explicit name override** in overlay: ``power_bi.report_name`` for
       Reports, ``power_bi.model_name`` for SemanticModels. When set, this
       wins unconditionally — it is the operator's declared intent. Use this
       to disambiguate when the source folder name doesn't match the target
       (the historical model-routing bug: source ``project.SemanticModel`` +
       overlay ``model_name: project_qa`` was silently routed to PROD
       ``project`` because only ``model_suffix`` was honoured).

    2. **Base + env suffix** (legacy path, retained): strip the
       ``.{ItemType}`` suffix from the local folder name and append the
       overlay-defined env suffix (``report_suffix`` / ``model_suffix``).
       With anti-double-suffix and optional source-strip from F10 fix
       (2026-05-24 earlier).

    The previous default ignored ``model_name`` / ``model_id`` entirely
    for routing — only the preflight block read them, informationally.
    """
    last_segment = local_path.rstrip("/").split("/")[-1]
    base = last_segment.removesuffix(f".{item_type}")
    pbi = overlay.get("power_bi") or {}

    if item_type == "Report":
        explicit_name = pbi.get("report_name")
        suffix = pbi.get("report_suffix", "") or ""
        strip_suffix = pbi.get("report_strip_suffix", "") or ""
    elif item_type == "SemanticModel":
        explicit_name = pbi.get("model_name")
        suffix = pbi.get("model_suffix", "") or ""
        strip_suffix = pbi.get("model_strip_suffix", "") or ""
    else:
        return base

    # Priority 1: explicit overlay name wins.
    if explicit_name:
        return explicit_name

    # Priority 2: base + env suffix (with anti-double-suffix + source-strip).
    if strip_suffix and base.endswith(strip_suffix):
        base = base[: -len(strip_suffix)]

    if not suffix:
        return base
    if base.endswith(suffix):
        return base
    return f"{base}{suffix}"


def _resolve_target_workspace(
    item_type: str, env_config: dict, overlay: dict,
) -> str | None:
    """Pick the workspace id where a push should land for this item type.

    Priority for Report:
        ``overlay.power_bi.report_workspace_id`` → ``overlay.fabric.workspace_id``
        → ``env_config.platforms.fabric.workspace_id``.
    Priority for SemanticModel:
        ``overlay.power_bi.model_workspace_id`` → same fallbacks.
    """
    pbi = overlay.get("power_bi") or {}
    fabric_overlay = overlay.get("fabric") or {}
    fabric_env = env_config.get("platforms", {}).get("fabric", {})

    if item_type == "Report":
        candidates = [
            pbi.get("report_workspace_id"),
            fabric_overlay.get("workspace_id"),
            fabric_env.get("workspace_id"),
        ]
    elif item_type == "SemanticModel":
        candidates = [
            pbi.get("model_workspace_id"),
            fabric_overlay.get("workspace_id"),
            fabric_env.get("workspace_id"),
        ]
    else:
        candidates = [fabric_overlay.get("workspace_id"), fabric_env.get("workspace_id")]

    for c in candidates:
        if c:
            return c
    return None


def _rebind_pbir_to_connection(
    parts: dict[str, bytes], model_id: str,
) -> dict[str, bytes]:
    """Rewrite ``definition.pbir`` to a ``byConnection`` reference.

    Mirrors the ADE deploy lifecycle (test_deploy_demo.py): every push goes
    out with a fixed byConnection payload pointing at the target model id.
    This makes the same source folder deployable across envs without manual
    edits to the .pbir.

    If the folder doesn't contain ``definition.pbir`` (e.g. PBIR-Legacy
    reports stored as a monolithic ``report.json``), the parts dict is
    returned unchanged.
    """
    if "definition.pbir" not in parts:
        return parts
    pbir = {
        "$schema": (
            "https://developer.microsoft.com/json-schemas/fabric/item/report/"
            "definitionProperties/2.0.0/schema.json"
        ),
        "version": "4.0",
        "datasetReference": {
            "byConnection": {
                "connectionString": (
                    f"Data Source=pbiazure://api.powerbi.com;"
                    f"Initial Catalog=abc;semanticModelId={model_id}"
                ),
            }
        },
    }
    rebound = dict(parts)
    rebound["definition.pbir"] = json.dumps(pbir, indent=2).encode("utf-8")
    return rebound


def _load_part_metadata(parts: dict[str, bytes]) -> dict | None:
    """Read the .fabric.json sidecar written by :meth:`pull_object`."""
    raw = parts.get(".fabric.json")
    if not raw:
        return None
    try:
        meta = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not meta.get("workspace_id") or not meta.get("item_id"):
        return None
    return meta


def _safe_filename(name: str) -> str:
    """Replace filesystem-unsafe characters in a display name."""
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name).strip("_")
