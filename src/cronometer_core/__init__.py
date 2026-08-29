"""cronometer-core — shared Python core for the Cronometer CLI and MCP server.

The API client, auth, CSV parsers, and business logic live here once; the
``click`` CLI (:mod:`cronometer_core.cli`) and the FastMCP server
(:mod:`cronometer_core.mcp_server`) are thin adapters generated from
:data:`cronometer_core.spec.OPERATIONS`.

Only lightweight, dependency-safe names are re-exported here so that importing
``cronometer_core`` never pulls in FastMCP (kept out of
:mod:`cronometer_core.mcp_server` until explicitly needed).
"""
from __future__ import annotations

from .auth import (
    AuthProvider,
    JsonFileTokenStore,
    NullTokenStore,
    PasswordSessionAuth,
    RequestParts,
    TokenStore,
)
from .client import CronometerClient
from .config import Config, resolve_auth, resolve_config
from .errors import CronometerError

__all__ = [
    "AuthProvider",
    "Config",
    "CronometerClient",
    "CronometerError",
    "JsonFileTokenStore",
    "NullTokenStore",
    "PasswordSessionAuth",
    "RequestParts",
    "TokenStore",
    "__version__",
    "resolve_auth",
    "resolve_config",
]

__version__ = "1.0.0"
