"""Pluggable authentication for the shared core.

The HTTP client delegates all credential handling to an :class:`AuthProvider`,
so services with different auth models can share one client and one ``spec.py``
→ CLI+MCP generation path. Providers live *below* the operations layer, so
``operations``/``spec``/``cli``/``mcp_server`` never change when the auth model
does.

Cronometer's model is a **username/password session** established via a GWT-RPC
login handshake (:class:`PasswordSessionAuth`), ported verbatim from the skill's
``cronometer_client.py``. The :class:`TokenStore` types are the persistence seam
providers may use; cronometer re-logs-in per process, so it uses
:class:`NullTokenStore`.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import requests

from .errors import AuthenticationError, NetworkError


@dataclass
class RequestParts:
    """The mutable pieces of an outgoing request a provider may decorate.

    Cookie-based auth (e.g. cronometer) is handled via the client's shared
    ``requests.Session`` cookie jar, which such providers own directly.
    """

    headers: dict[str, str] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class AuthProvider(Protocol):
    """Authenticates outgoing requests and reacts to auth failures."""

    def prepare(self, req: RequestParts) -> None:
        """Ensure valid credentials (may lazily log in / refresh) and decorate
        ``req`` (headers and/or params)."""

    def on_auth_failure(self, response: Any) -> bool:
        """Called on a 401/403. Return ``True`` if credentials were refreshed
        and the request should be retried **once**, ``False`` to surface the
        error to the caller."""


# --- Token stores ---------------------------------------------------------
@runtime_checkable
class TokenStore(Protocol):
    """Persistence for credential state (refresh tokens, sessions)."""

    def load(self) -> dict | None: ...

    def save(self, tokens: dict) -> None: ...


class NullTokenStore:
    """In-memory only — for providers that re-authenticate per process
    (cronometer: re-login each run)."""

    def load(self) -> dict | None:
        return None

    def save(self, tokens: dict) -> None:
        return None


class JsonFileTokenStore:
    """Atomic JSON file store (write-temp-then-``os.replace``).

    Atomicity matters: a rotating OAuth refresh token is single-use, so a crash
    mid-write must never leave a truncated file — you either keep the old token
    or get the new one, never nothing. Default path is honoured verbatim; the
    caller resolves any env/default logic.
    """

    def __init__(self, path: str) -> None:
        self.path = os.path.expanduser(path)

    def load(self) -> dict | None:
        try:
            with open(self.path, encoding="utf-8") as fh:
                return json.load(fh)
        except (FileNotFoundError, ValueError):
            return None

    def save(self, tokens: dict) -> None:
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory or ".", prefix=".tokens-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(tokens, fh)
            os.replace(tmp, self.path)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise


# --- Cronometer GWT-RPC auth (ported verbatim from cronometer_client.py) ---
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# GWT magic values (verbatim from the skill's lib/gwt-values.ts port).
GWT_VALUES = {
    "contentType": "text/x-gwt-rpc; charset=UTF-8",
    "moduleBase": "https://cronometer.com/cronometer/",
    "permutation": "F9A8D0A4A73CE43C69A1EC5994B87F20",  # Updated 2026-03-31
    "header": "F9A8D0A4A73CE43C69A1EC5994B87F20",        # Same as permutation
}

API_URLS = {
    "loginPage": "https://cronometer.com/login/",
    "login": "https://cronometer.com/login",
    "gwtApp": "https://cronometer.com/cronometer/app",
    "export": "https://cronometer.com/export",
    "apiV3Base": "https://cronometer.com/api/v3",
}


def get_targets_url(user_id: str) -> str:
    return f"{API_URLS['apiV3Base']}/user/{user_id}/targets"


def get_gwt_authenticate() -> str:
    return (
        f"7|0|5|https://cronometer.com/cronometer/|{GWT_VALUES['header']}|"
        "com.cronometer.shared.rpc.CronometerService|authenticate|"
        "java.lang.Integer/3438268394|1|2|3|4|1|5|5|-300|"
    )


def get_gwt_generate_auth_token(nonce: str, user_id: str) -> str:
    return (
        f"7|0|8|https://cronometer.com/cronometer/|{GWT_VALUES['header']}|"
        "com.cronometer.shared.rpc.CronometerService|generateAuthorizationToken|"
        "java.lang.String/2004016611|I|"
        f"com.cronometer.shared.user.AuthScope/2065601159|{nonce}|"
        f"1|2|3|4|4|5|6|6|7|8|{user_id}|3600|7|2|"
    )


def fetch_gwt_values() -> dict | None:
    """Fetch a fresh GWT permutation from Cronometer's bootstrap script."""
    try:
        r = requests.get(
            "https://cronometer.com/cronometer/cronometer.nocache.js",
            headers={"User-Agent": UA},
            timeout=30,
        )
        if not r.ok:
            return None
        m = re.search(r"='([A-F0-9]{32})'", r.text, re.I)
        if m:
            perm = m.group(1)
            return {"permutation": perm, "header": perm}
        return None
    except requests.RequestException:
        return None


def update_gwt_values(values: dict) -> None:
    GWT_VALUES["permutation"] = values["permutation"]
    GWT_VALUES["header"] = values["header"]


_gwt_initialized = {"done": False}


def ensure_gwt_values_initialized() -> None:
    if _gwt_initialized["done"]:
        return
    fresh = fetch_gwt_values()
    if fresh:
        update_gwt_values(fresh)
    _gwt_initialized["done"] = True


class PasswordSessionAuth:
    """Username/password session auth via Cronometer's GWT-RPC login handshake.

    Owns its own ``requests.Session`` (``self.session``): the login flow runs on
    it so every cookie (``sesnonce`` etc.) lands in one jar, and the client is
    wired to reuse that same session for the export/targets requests.

    The session holds an ~1h auth token; :meth:`prepare` lazily (re-)logs in
    when it is stale and adds ``nonce`` (the auth token) as a query param, which
    the ``/export`` endpoint needs and the targets endpoint tolerates.
    """

    def __init__(
        self,
        username: str,
        password: str,
        *,
        base_url: str = "https://cronometer.com",
        token_store: TokenStore | None = None,
    ) -> None:
        self.username = username
        self.password = password
        self.base_url = base_url
        self.token_store = token_store or NullTokenStore()
        self.session = requests.Session()
        self.session.headers["User-Agent"] = UA
        # SessionState: {nonce, userId, authToken, tokenExpiry(epoch ms)} | None
        self._state: dict[str, Any] | None = None

    # -- public accessors --------------------------------------------------
    @property
    def user_id(self) -> str:
        self._ensure_valid()
        assert self._state is not None
        return self._state["userId"]

    @property
    def auth_token(self) -> str:
        self._ensure_valid()
        assert self._state is not None
        return self._state["authToken"]

    @property
    def session_state(self) -> dict[str, Any] | None:
        return self._state

    def is_session_valid(self) -> bool:
        if not self._state:
            return False
        return time.time() * 1000.0 < self._state["tokenExpiry"]

    def clear_session(self) -> None:
        """Drop the session state and all cookies (keeping the same Session
        object so the client's injected reference stays valid)."""
        self._state = None
        self.session.cookies.clear()

    def reauth(self) -> None:
        """Force a full re-login regardless of current session validity."""
        self._ensure_valid(force=True)

    # -- AuthProvider protocol ---------------------------------------------
    def prepare(self, req: RequestParts) -> None:
        self._ensure_valid()
        req.params["nonce"] = self.auth_token

    def on_auth_failure(self, response: Any) -> bool:
        self._ensure_valid(force=True)
        return True

    # -- internals ---------------------------------------------------------
    def _ensure_valid(self, force: bool = False) -> None:
        if force or not self.is_session_valid():
            self.clear_session()
            self._login()

    def _login(self) -> dict[str, Any]:
        ensure_gwt_values_initialized()
        anticsrf = self._get_anticsrf_token()
        self._submit_login(anticsrf)
        user_id = self._gwt_authenticate()
        nonce = self._get_nonce_cookie()
        if not nonce:
            raise AuthenticationError("No session nonce after GWT authentication")
        auth_token = self._generate_auth_token(nonce, user_id)
        # tokenExpiry: now + 1 hour (epoch ms, mirrors the TS Date math).
        self._state = {
            "nonce": nonce,
            "userId": user_id,
            "authToken": auth_token,
            "tokenExpiry": (time.time() + 3600) * 1000.0,
        }
        return self._state

    def _get_anticsrf_token(self) -> str:
        try:
            r = self.session.get(
                API_URLS["loginPage"], headers={"User-Agent": UA}, timeout=30
            )
        except requests.RequestException as e:
            raise NetworkError(f"Failed to fetch login page: {e}") from e
        if not r.ok:
            raise NetworkError(f"Failed to fetch login page: {r.status_code}")
        m = re.search(r'name="anticsrf"\s+value="([^"]+)"', r.text)
        if not m:
            raise AuthenticationError("Could not find anticsrf token in login page")
        return m.group(1)

    def _submit_login(self, anticsrf: str) -> None:
        form = {
            "anticsrf": anticsrf,
            "username": self.username,
            "password": self.password,
        }
        r = self.session.post(
            API_URLS["login"],
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": UA,
            },
            data=form,
            allow_redirects=False,
            timeout=30,
        )
        nonce = self._get_nonce_cookie()
        if not nonce:
            text = r.text
            if "Too Many Attempts" in text:
                raise AuthenticationError(
                    "Rate limited by Cronometer: Too many login attempts. "
                    "Please wait a few minutes and try again."
                )
            try:
                err = json.loads(text)
                if isinstance(err, dict) and err.get("error"):
                    raise AuthenticationError(f"Login failed: {err['error']}")
            except AuthenticationError:
                raise
            except Exception:  # noqa: S110 — non-JSON body: fall through
                pass
            raise AuthenticationError(
                "Login failed: no session cookie received. Check username/password."
            )

    def _gwt_authenticate(self, retry_on_failure: bool = True) -> str:
        r = self.session.post(
            API_URLS["gwtApp"],
            headers={
                "Content-Type": GWT_VALUES["contentType"],
                "X-GWT-Module-Base": GWT_VALUES["moduleBase"],
                "X-GWT-Permutation": GWT_VALUES["permutation"],
                "User-Agent": UA,
            },
            data=get_gwt_authenticate().encode("utf-8"),
            timeout=30,
        )
        if r.status_code == 500 and retry_on_failure:
            fresh = fetch_gwt_values()
            if fresh:
                update_gwt_values(fresh)
                return self._gwt_authenticate(False)
        if not r.ok:
            raise AuthenticationError(f"GWT authenticate failed: {r.status_code}")
        body = r.text
        m = re.search(r"OK\[(\d+),", body)
        if not m:
            raise AuthenticationError(
                f"Could not extract user ID from GWT response: {body[:100]}"
            )
        return m.group(1)

    def _generate_auth_token(
        self, nonce: str, user_id: str, retry_on_failure: bool = True
    ) -> str:
        body = get_gwt_generate_auth_token(nonce, user_id)
        r = self.session.post(
            API_URLS["gwtApp"],
            headers={
                "Content-Type": GWT_VALUES["contentType"],
                "X-GWT-Module-Base": GWT_VALUES["moduleBase"],
                "X-GWT-Permutation": GWT_VALUES["permutation"],
                "User-Agent": UA,
            },
            data=body.encode("utf-8"),
            timeout=30,
        )
        if r.status_code == 500 and retry_on_failure:
            fresh = fetch_gwt_values()
            if fresh:
                update_gwt_values(fresh)
                return self._generate_auth_token(nonce, user_id, False)
        if not r.ok:
            raise AuthenticationError(f"Generate auth token failed: {r.status_code}")
        body_text = r.text
        m = re.search(r'"([^"]+)"', body_text)
        if not m:
            raise AuthenticationError(
                f"Could not extract auth token from response: {body_text[:100]}"
            )
        return m.group(1)

    def _get_nonce_cookie(self) -> str | None:
        return self.session.cookies.get("sesnonce")
