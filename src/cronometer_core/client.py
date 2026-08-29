"""HTTP client for Cronometer.

A thin, typed wrapper over ``requests`` with a request timeout and retry/backoff
with rate-limit handling. Auth is delegated to an :class:`AuthProvider`
(cronometer uses :class:`~cronometer_core.auth.PasswordSessionAuth`, a
username/password session). Returns parsed JSON, or the raw text body for
non-JSON responses (Cronometer's ``/export`` returns CSV); raises a typed
:class:`~cronometer_core.errors.CronometerError` on failure.

The client only knows how to talk HTTP — all endpoint/business logic lives in
:mod:`cronometer_core.operations`, so both the CLI and MCP share one client.
"""
from __future__ import annotations

import contextlib
import time
from collections.abc import Callable, Mapping
from typing import Any

import requests

from .auth import AuthProvider, RequestParts
from .config import Config, resolve_auth, resolve_config
from .errors import NetworkError, RateLimitError, error_for_status

AUTH_FAILURE_STATUSES = frozenset({401, 403})

DEFAULT_TIMEOUT = 60
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF = 0.5
# Only retry methods that are safe to repeat.
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "DELETE"})
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

JsonValue = Any


class CronometerClient:
    """Talks to Cronometer over HTTP.

    Args:
        config: Resolved :class:`Config`. If omitted, resolved from the
            environment via :func:`~cronometer_core.config.resolve_config`.
        auth: The :class:`AuthProvider`. Adapters inject a
            :class:`~cronometer_core.auth.PasswordSessionAuth` (and its session);
            if omitted, one is built from ``config`` via ``resolve_auth`` and its
            session is reused so login cookies and requests share one jar.
        timeout: Per-request timeout in seconds.
        max_retries: Retry attempts for idempotent requests on transient
            failures (network errors and ``RETRY_STATUSES``).
        backoff: Base seconds for exponential backoff between retries.
        session: Optional pre-built ``requests.Session`` (injectable for tests);
            defaults to the auth provider's own session when it has one.
        sleep: Sleep function (injectable so tests don't actually wait).
    """

    def __init__(
        self,
        config: Config | None = None,
        *,
        auth: AuthProvider | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff: float = DEFAULT_BACKOFF,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config or resolve_config()
        self.base_url = self.config.base_url
        # Auth is delegated to a provider (below the operations layer). Build one
        # from config if the caller did not inject it.
        self.auth: AuthProvider = auth or resolve_auth(self.config)
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self._sleep = sleep
        # Reuse the provider's own session (so login cookies + requests share one
        # cookie jar) unless a session was explicitly injected.
        self.session = session or getattr(self.auth, "session", None) or requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    # -- low level ---------------------------------------------------------
    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any | None = None,
    ) -> JsonValue:
        """Perform an HTTP request and return parsed JSON (or ``None`` if empty).

        Retries idempotent requests on transient failures with exponential
        backoff, honouring a ``Retry-After`` header on 429 responses.
        """
        method = method.upper()
        url = f"{self.base_url}{path}"
        retriable = method in IDEMPOTENT_METHODS
        attempt = 0
        auth_retried = False
        while True:
            req = RequestParts(params=dict(self._clean_params(params) or {}))
            self.auth.prepare(req)
            try:
                response = self.session.request(
                    method,
                    url,
                    params=req.params or None,
                    json=json,
                    headers=req.headers or None,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                if retriable and attempt < self.max_retries:
                    self._wait(attempt)
                    attempt += 1
                    continue
                raise NetworkError(
                    f"Cronometer {method} {path} request failed: {exc}"
                ) from exc

            # Auth-refresh retry (distinct from the transient-status retry): let
            # the provider refresh once on a 401/403, then retry the request.
            if (
                response.status_code in AUTH_FAILURE_STATUSES
                and not auth_retried
                and self.auth.on_auth_failure(response)
            ):
                auth_retried = True
                continue

            if response.status_code in RETRY_STATUSES and (
                retriable and attempt < self.max_retries
            ):
                self._wait(attempt, response)
                attempt += 1
                continue

            if response.status_code >= 400:
                if response.status_code == 429:
                    raise RateLimitError(
                        "Cronometer rate limit exceeded (429). Try again later.",
                        status=429,
                        body=response.text,
                    )
                raise error_for_status(response.status_code, response.text)

            return self._parse(response)

    def _wait(self, attempt: int, response: requests.Response | None = None) -> None:
        delay = self.backoff * (2**attempt)
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                with contextlib.suppress(ValueError):
                    delay = max(delay, float(retry_after))
        self._sleep(delay)

    @staticmethod
    def _clean_params(params: Mapping[str, Any] | None) -> dict[str, Any] | None:
        """Drop ``None`` values so they aren't serialised as ``"None"``."""
        if not params:
            return None
        return {k: v for k, v in params.items() if v is not None}

    @staticmethod
    def _parse(response: requests.Response) -> JsonValue:
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            # Non-JSON bodies (e.g. the CSV export) pass through as text.
            return response.text

    # -- verb helpers ------------------------------------------------------
    def get(self, path: str, params: Mapping[str, Any] | None = None) -> JsonValue:
        return self.request("GET", path, params=params)

    def post(self, path: str, json: Any | None = None) -> JsonValue:
        return self.request("POST", path, json=json)

    def put(self, path: str, json: Any | None = None) -> JsonValue:
        return self.request("PUT", path, json=json)

    def delete(self, path: str) -> JsonValue:
        return self.request("DELETE", path)
