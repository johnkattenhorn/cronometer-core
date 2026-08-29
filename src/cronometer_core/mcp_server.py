"""FastMCP server generated from :data:`cronometer_core.spec.OPERATIONS`.

Every operation becomes an MCP tool with the same name and parameters as the
corresponding CLI subcommand — a 1:1 wrapper by construction. Tools return
normalised JSON (structured content); read tools accept ``text=true`` to return
the human-readable view instead. Served over Streamable HTTP with an
unauthenticated ``/health`` endpoint for the reverse proxy and uptime checks.
"""
from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from inspect import Parameter, Signature
from typing import Any

from .client import CronometerClient
from .config import resolve_auth, resolve_config
from .errors import ValidationError
from .format import to_text
from .spec import BOOL, EXERCISES, INT, OPERATIONS, Op, Param

log = logging.getLogger("cronometer")

SERVER_NAME = "cronometer-mcp"
DEFAULT_PUBLIC_URL = "http://localhost:3000"



def public_url() -> str:
    """Externally reachable base URL — the OAuth issuer and resource identifier."""
    return os.environ.get("CRONOMETER_PUBLIC_URL", DEFAULT_PUBLIC_URL).rstrip("/")


def _load_token_map() -> dict[str, dict[str, Any]]:
    """Parse ``CRONOMETER_TOKENS``; empty dict means "no in-app auth"."""
    raw = os.environ.get("CRONOMETER_TOKENS", "").strip()
    if not raw:
        return {}
    try:
        tokens = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"CRONOMETER_TOKENS is not valid JSON: {exc}") from exc
    if not isinstance(tokens, dict) or not tokens:
        raise ValidationError("CRONOMETER_TOKENS must be a non-empty JSON object")
    for token, claims in tokens.items():
        if not isinstance(claims, dict):
            raise ValidationError(f"claims for token {token[:6]}... must be an object")
        claims.setdefault("client_id", "cronometer-client")
        claims.setdefault("scopes", [])
    return tokens


AUTH_MODES = ("none", "token", "oauth", "oidc")


def _oidc_settings() -> tuple[str, str, str]:
    """Upstream OIDC coordinates, or a clear error naming what is missing."""
    missing = [
        name
        for name in (
            "CRONOMETER_OIDC_CONFIG_URL",
            "CRONOMETER_OIDC_CLIENT_ID",
            "CRONOMETER_OIDC_CLIENT_SECRET",
        )
        if not os.environ.get(name, "").strip()
    ]
    if missing:
        raise ValidationError(f"CRONOMETER_AUTH=oidc requires {', '.join(missing)}")
    return (
        os.environ["CRONOMETER_OIDC_CONFIG_URL"].strip(),
        os.environ["CRONOMETER_OIDC_CLIENT_ID"].strip(),
        os.environ["CRONOMETER_OIDC_CLIENT_SECRET"].strip(),
    )


def _with_static_tokens(auth: Any) -> Any:
    """Compose static bearer tokens alongside an OAuth provider, if any are set."""
    tokens = _load_token_map()
    if not tokens:
        return auth
    from fastmcp.server.auth import MultiAuth
    from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

    log.info("plus %d static bearer token(s) for non-browser clients", len(tokens))
    return MultiAuth(
        server=auth,
        verifiers=[StaticTokenVerifier(tokens=tokens)],
        base_url=public_url(),
    )


def _build_oidc_auth() -> Any:
    """OAuth delegated upstream via fastmcp's OIDCProxy (which shims DCR).

    client_storage is left at fastmcp's default: an encrypted file store under
    FASTMCP_HOME. Its directory is a fingerprint of the JWT signing key, which
    OIDCProxy derives from client_secret — a stable value — so registrations and
    tokens survive a restart provided FASTMCP_HOME is a mounted volume. If it is
    not, this silently behaves like `oauth`.
    """
    from fastmcp.server.auth.oidc_proxy import OIDCProxy

    config_url, client_id, client_secret = _oidc_settings()
    auth = OIDCProxy(
        config_url=config_url,
        client_id=client_id,
        client_secret=client_secret,
        base_url=public_url(),
    )
    log.info("oidc auth via %s (base_url=%s)", config_url, public_url())
    return _with_static_tokens(auth)


def resolve_auth_mode() -> str:
    """Which inbound auth this process uses: ``none``, ``token`` or ``oauth``."""
    explicit = os.environ.get("CRONOMETER_AUTH", "").strip().lower()
    if explicit:
        if explicit not in AUTH_MODES:
            raise ValidationError(
                f"CRONOMETER_AUTH must be one of {', '.join(AUTH_MODES)} "
                f"(got {explicit!r})"
            )
        return explicit
    return "token" if os.environ.get("CRONOMETER_TOKENS", "").strip() else "none"


def _build_auth() -> Any:
    """Resolve the inbound auth provider from the environment (``None`` = open)."""
    auth_mode = resolve_auth_mode()
    if auth_mode == "oidc":
        return _build_oidc_auth()
    if auth_mode == "token":
        from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

        tokens = _load_token_map()
        if not tokens:
            raise ValidationError("CRONOMETER_AUTH=token requires CRONOMETER_TOKENS")
        log.info("bearer auth enabled for %d token(s)", len(tokens))
        return StaticTokenVerifier(tokens=tokens)
    if auth_mode == "oauth":
        from fastmcp.server.auth.providers.in_memory import InMemoryOAuthProvider
        from mcp.server.auth.settings import ClientRegistrationOptions

        auth = InMemoryOAuthProvider(
            base_url=public_url(),
            client_registration_options=ClientRegistrationOptions(enabled=True),
        )
        log.info("oauth enabled at %s", public_url())
        tokens = _load_token_map()
        if tokens:
            from fastmcp.server.auth import MultiAuth
            from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

            auth = MultiAuth(
                server=auth,
                verifiers=[StaticTokenVerifier(tokens=tokens)],
                base_url=public_url(),
            )
            log.info("plus %d static bearer token(s) for non-browser clients", len(tokens))
        return auth
    log.warning(
        "no in-app auth (CRONOMETER_AUTH=none) — relying on the Traefik IP allow-list alone"
    )
    return None

_BASE_TYPES: dict[str, type] = {INT: int, "str": str, BOOL: bool}


def _annotation_and_default(param: Param) -> tuple[Any, Any]:
    """Map a spec :class:`Param` to a Python annotation + default for the tool."""
    if param.kind == EXERCISES:
        assert param.exercises_model is not None
        return list[param.exercises_model], Parameter.empty  # type: ignore[name-defined]
    base = _BASE_TYPES[param.kind]
    if param.required:
        return base, Parameter.empty
    if param.default is None:
        return base | None, None
    return base, param.default


def _make_impl(op: Op, get_client: Callable[[], CronometerClient]) -> Callable[..., Any]:
    """Build a tool implementation with a real signature FastMCP can introspect."""

    def impl(**kwargs: Any) -> Any:
        text = bool(kwargs.pop("text", False)) if op.formatted else False
        result = op.func(get_client(), **kwargs)
        return to_text(result) if text else result

    parameters: list[Parameter] = []
    annotations: dict[str, Any] = {}
    for param in op.params:
        annotation, default = _annotation_and_default(param)
        parameters.append(
            Parameter(param.name, Parameter.KEYWORD_ONLY, default=default, annotation=annotation)
        )
        annotations[param.name] = annotation
    if op.formatted:
        parameters.append(
            Parameter("text", Parameter.KEYWORD_ONLY, default=False, annotation=bool)
        )
        annotations["text"] = bool

    impl.__signature__ = Signature(parameters)  # type: ignore[attr-defined]
    annotations["return"] = Any
    impl.__annotations__ = annotations
    impl.__name__ = op.name.replace("-", "_")
    impl.__doc__ = op.help
    return impl


def build_server(client: CronometerClient | None = None) -> Any:
    """Construct (but do not run) the FastMCP server with all tools registered.

    ``client`` may be injected for tests; otherwise it is created lazily from the
    environment on first tool call so importing the server never requires
    credentials.
    """
    from fastmcp import FastMCP
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    mcp = FastMCP(SERVER_NAME, auth=_build_auth())

    _cached: dict[str, CronometerClient] = {}

    def get_client() -> CronometerClient:
        if client is not None:
            return client
        if "c" not in _cached:
            config = resolve_config()
            auth = resolve_auth(config)
            _cached["c"] = CronometerClient(config, auth=auth, session=auth.session)
        return _cached["c"]

    for op in OPERATIONS:
        impl = _make_impl(op, get_client)
        mcp.tool(name=op.name, description=op.help)(impl)

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "service": SERVER_NAME})

    return mcp


def main() -> None:
    """Entry point: run the server over the configured transport."""
    # Uppercase and fall back: logging.basicConfig raises ValueError on an
    # unknown level, which would kill the process at boot before anything is
    # served. Deployment .env files commonly carry lowercase LOG_LEVEL values.
    level = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
    if level not in ("CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"):
        level = "INFO"
    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=level)
    transport = os.environ.get("MCP_TRANSPORT", "http")
    host = os.environ.get("HOST", "0.0.0.0")  # noqa: S104 — container binds all
    port = int(os.environ.get("PORT", "3000"))
    server = build_server()
    if transport in ("http", "streamable-http"):
        server.run(transport="http", host=host, port=port)
    else:
        server.run()


if __name__ == "__main__":
    main()
