"""Base connector protocol for ade-ops platform integrations.

All platform connectors must implement this interface. The engine calls
these methods without knowing which platform it's talking to.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PlatformConnector(Protocol):
    """Interface that all platform connectors must implement.

    Connectors handle platform-specific API calls. The engine handles
    orchestration, overlay transforms, state tracking, and file I/O.
    """

    def list_objects(
        self,
        env_config: dict,
        overlay: dict,
        *,
        pipeline_filter: str | None = None,
    ) -> list[dict]:
        """List all objects in the remote environment.

        Returns a list of dicts with:
            - path: str (remote path, used for pull_object)
            - local_path: str (relative path for local storage)
            - type: str ("NOTEBOOK", "FILE", "MODEL", "REPORT", etc.)
            - modified: str (ISO timestamp, best effort)
        """
        ...

    def pull_object(self, remote_path: str) -> bytes | str | None:
        """Download a single object's content from the remote.

        Returns content as bytes or str, or None on failure.
        """
        ...

    def push_object(
        self,
        local_path: str,
        content: bytes,
        env_config: dict,
        overlay: dict,
    ) -> bool:
        """Upload content to a remote path.

        Args:
            local_path: Relative path of the file being pushed.
            content: File content (already transformed by overlay).
            env_config: Environment configuration from project.yaml.
            overlay: Overlay configuration dict.

        Returns:
            True on success.
        """
        ...

    def get_hash(self, remote_path: str) -> str | None:
        """Get a content hash for a remote object (for conflict detection).

        Returns hash string, or None if not available.
        """
        ...
