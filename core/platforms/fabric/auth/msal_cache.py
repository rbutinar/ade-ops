"""Fabric MSAL authentication with persistent token cache.

Provides interactive browser authentication for Microsoft Fabric APIs and
Fabric Warehouse SQL connections, with a persistent on-disk token cache so
the user is not prompted on every call.

The cache path (``~/.ade/fabric_token_cache.json``) is intentionally shared
with the ADE lab — users who run both ade-ops and ADE on the same machine
only have to authenticate once.

Typical usage::

    from core.platforms.fabric.auth import get_fabric_token, get_sql_token

    token = get_fabric_token(tenant="contoso.com", login_hint="user@example.com")
    sql_token = get_sql_token(tenant="contoso.com")

For pyodbc ``ActiveDirectoryAccessToken`` connections, use
:func:`get_sql_token_struct` which returns the packed token struct directly.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Optional

# =============================================================================
# Configuration
# =============================================================================

# Default tenant — overridable per-call.
DEFAULT_TENANT = "common"

# Azure CLI public client id — supports the interactive browser flow for
# Microsoft APIs. This is a well-known public client; nothing secret to it.
AZURE_CLI_CLIENT_ID = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"

# Scopes per resource.
SCOPES_FABRIC_API = ["https://api.fabric.microsoft.com/.default"]
SCOPES_SQL = ["https://database.windows.net/.default"]

# Persistent cache location (shared with the ADE lab on purpose).
CACHE_DIR = Path.home() / ".ade"
CACHE_FILE = CACHE_DIR / "fabric_token_cache.json"


# =============================================================================
# Internal state
# =============================================================================

_token_cache = None  # msal.SerializableTokenCache, lazily created
_msal_apps: dict = {}  # tenant -> msal.PublicClientApplication


def _ensure_cache_dir() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _get_token_cache():
    """Return the lazily-loaded persistent token cache."""
    global _token_cache
    if _token_cache is None:
        import msal  # lazy import

        _token_cache = msal.SerializableTokenCache()
        _ensure_cache_dir()
        if CACHE_FILE.exists():
            try:
                _token_cache.deserialize(CACHE_FILE.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001 — cache corruption is non-fatal
                print(f"Warning: could not load token cache: {e}")
    return _token_cache


def _save_token_cache() -> None:
    if _token_cache is not None and _token_cache.has_state_changed:
        try:
            _ensure_cache_dir()
            CACHE_FILE.write_text(_token_cache.serialize(), encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            print(f"Warning: could not save token cache: {e}")


def _get_msal_app(tenant: str | None = None):
    """Return the MSAL public client for ``tenant`` (memoised)."""
    import msal  # lazy import

    tenant = tenant or DEFAULT_TENANT
    if tenant not in _msal_apps:
        cache = _get_token_cache()
        authority = f"https://login.microsoftonline.com/{tenant}"
        _msal_apps[tenant] = msal.PublicClientApplication(
            AZURE_CLI_CLIENT_ID,
            authority=authority,
            token_cache=cache,
        )
    return _msal_apps[tenant]


# =============================================================================
# Token acquisition
# =============================================================================

def get_token(
    scopes: list[str],
    *,
    tenant: str | None = None,
    silent_only: bool = False,
    verbose: bool = True,
    login_hint: str | None = None,
) -> Optional[str]:
    """Acquire an access token for ``scopes`` via the persistent cache.

    Tries the cache first. If no valid token is available, falls back to an
    interactive browser login (unless ``silent_only=True``).

    Args:
        scopes: list of token scopes (use ``SCOPES_FABRIC_API`` or ``SCOPES_SQL``).
        tenant: tenant id or domain (default: ``"common"``).
        silent_only: if true, only try the cache — never prompt.
        verbose: print one-line status messages.
        login_hint: email to pre-fill in the browser flow.

    Returns:
        Access token string, or ``None`` on failure.
    """
    app = _get_msal_app(tenant)
    accounts = app.get_accounts()
    if accounts:
        if verbose:
            print(f"  Found cached account: {accounts[0]['username']}")
        result = app.acquire_token_silent(scopes, account=accounts[0])
        if result and "access_token" in result:
            if verbose:
                print("  Using cached token")
            _save_token_cache()
            return result["access_token"]

    if silent_only:
        return None

    if verbose:
        print("  Opening browser for authentication...")
        if login_hint:
            print(f"  Login hint: {login_hint}")

    try:
        result = app.acquire_token_interactive(scopes=scopes, login_hint=login_hint)
    except Exception as e:  # noqa: BLE001
        if verbose:
            print(f"  Interactive login failed: {e}")
        return None

    if "access_token" in result:
        if verbose:
            print("  Authentication successful")
        _save_token_cache()
        return result["access_token"]

    if verbose:
        err = result.get("error", "unknown")
        desc = (result.get("error_description") or "")[:200]
        print(f"  Authentication failed: {err}")
        if desc:
            print(f"    {desc}")
    return None


def get_fabric_token(
    *, tenant: str | None = None, silent_only: bool = False,
    verbose: bool = True, login_hint: str | None = None,
) -> Optional[str]:
    """Get a Fabric REST API token (scope ``https://api.fabric.microsoft.com``)."""
    return get_token(
        SCOPES_FABRIC_API,
        tenant=tenant, silent_only=silent_only, verbose=verbose, login_hint=login_hint,
    )


def get_sql_token(
    *, tenant: str | None = None, silent_only: bool = False,
    verbose: bool = True, login_hint: str | None = None,
) -> Optional[str]:
    """Get a SQL connection token (scope ``https://database.windows.net``)."""
    return get_token(
        SCOPES_SQL,
        tenant=tenant, silent_only=silent_only, verbose=verbose, login_hint=login_hint,
    )


def get_sql_token_struct(
    *, tenant: str | None = None, login_hint: str | None = None,
) -> tuple[bytes | None, str | None]:
    """Return the SQL token packed for pyodbc ``ActiveDirectoryAccessToken``.

    Returns ``(token_struct, raw_token)`` or ``(None, None)`` on failure.

    Use with pyodbc like::

        token_struct, _ = get_sql_token_struct(tenant="contoso.com")
        conn = pyodbc.connect(
            "Driver={ODBC Driver 17 for SQL Server};...",
            attrs_before={1256: token_struct},
        )
    """
    token = get_sql_token(tenant=tenant, login_hint=login_hint)
    if not token:
        return None, None
    token_bytes = token.encode("utf-16-le")
    token_struct = struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)
    return token_struct, token


# =============================================================================
# Cache management
# =============================================================================

def clear_cache() -> None:
    """Delete the persistent cache and reset in-memory state."""
    global _token_cache, _msal_apps
    if CACHE_FILE.exists():
        CACHE_FILE.unlink()
        print(f"Deleted cache file: {CACHE_FILE}")
    _token_cache = None
    _msal_apps = {}
    print("Token cache cleared")


def get_current_user(*, tenant: str | None = None) -> Optional[str]:
    """Return the username of the (first) cached account, if any."""
    app = _get_msal_app(tenant)
    accounts = app.get_accounts()
    if accounts:
        return accounts[0].get("username")
    return None


def get_cache_info() -> dict:
    """Return the cache path, size, and the cached accounts (best effort)."""
    info = {
        "cache_file": str(CACHE_FILE),
        "exists": CACHE_FILE.exists(),
        "size_bytes": CACHE_FILE.stat().st_size if CACHE_FILE.exists() else 0,
        "accounts": [],
    }
    if CACHE_FILE.exists():
        _get_token_cache()  # ensure loaded
        for tenant, app in _msal_apps.items():
            for account in app.get_accounts():
                info["accounts"].append({
                    "username": account.get("username"),
                    "tenant": tenant,
                })
    return info


# =============================================================================
# CLI (mirror of ADE's, useful for debugging)
# =============================================================================

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Fabric MSAL authentication")
    parser.add_argument("--tenant", help="Tenant id or domain")
    parser.add_argument("--clear", action="store_true", help="Clear token cache")
    parser.add_argument("--test", action="store_true", help="Test Fabric API token")
    parser.add_argument("--sql", action="store_true", help="Test SQL token")
    parser.add_argument("--info", action="store_true", help="Show cache info")
    parser.add_argument("--login-hint", help="Email to pre-fill in the browser flow")
    args = parser.parse_args()

    print("=" * 60)
    print("FABRIC MSAL AUTHENTICATION")
    print("=" * 60)
    print(f"Cache: {CACHE_FILE}")

    if args.clear:
        clear_cache()
        return

    if args.info:
        info = get_cache_info()
        print(f"\nCache file: {info['cache_file']}")
        print(f"Exists: {info['exists']}")
        print(f"Size: {info['size_bytes']} bytes")
        if info["accounts"]:
            print("\nCached accounts:")
            for acc in info["accounts"]:
                print(f"  - {acc['username']} ({acc['tenant']})")
        return

    if args.test or args.sql:
        print("\n[Testing authentication]")
        scope = "SQL" if args.sql else "Fabric API"
        token = (get_sql_token if args.sql else get_fabric_token)(
            tenant=args.tenant, login_hint=args.login_hint,
        )
        if token:
            print(f"\n{scope} token obtained — length {len(token)} chars")
        else:
            print(f"\nFailed to get {scope} token")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
