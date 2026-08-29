"""Error taxonomy for cronometer-core.

A single :class:`CronometerError` base with typed subclasses so both the CLI and
the MCP server can categorise failures consistently (and tests can assert on
type rather than string-matching a message).
"""
from __future__ import annotations

from enum import Enum


class ErrorType(str, Enum):
    """Coarse category for a Cronometer failure, surfaced to callers."""

    VALIDATION = "validation"
    AUTHENTICATION = "authentication"
    NOT_FOUND = "not_found"
    RATE_LIMIT = "rate_limit"
    API = "api"
    NETWORK = "network"
    UNKNOWN = "unknown"


class CronometerError(Exception):
    """Base class for every error raised by cronometer-core.

    ``error_type`` categorises the failure; ``status`` carries the HTTP status
    when the failure originated from an API response; ``body`` is the raw
    response text (if any) for diagnostics.
    """

    error_type: ErrorType = ErrorType.UNKNOWN

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.body = body

    def to_dict(self) -> dict[str, object]:
        """Serialise for the CLI's ``{"ok": false, ...}`` error envelope."""
        out: dict[str, object] = {
            "ok": False,
            "error": self.message,
            "type": self.error_type.value,
        }
        if self.status is not None:
            out["status"] = self.status
        return out


class ValidationError(CronometerError):
    """Bad input caught before (or by) the API — clamp/validation failures."""

    error_type = ErrorType.VALIDATION


class AuthenticationError(CronometerError):
    """Missing/invalid credentials or a failed login handshake (HTTP 401/403)."""

    error_type = ErrorType.AUTHENTICATION


class ReauthRequiredError(AuthenticationError):
    """Credentials are unrecoverable and an interactive re-login is required.

    Raised by session/OAuth providers when a refresh fails terminally (e.g. a
    rotating refresh token was invalidated), so callers get an actionable
    "re-run login" message instead of a bare 401.
    """


class NotFoundError(CronometerError):
    """The requested resource does not exist (HTTP 404)."""

    error_type = ErrorType.NOT_FOUND


class RateLimitError(CronometerError):
    """The Cronometer API rate limit was hit (HTTP 429)."""

    error_type = ErrorType.RATE_LIMIT


class ApiError(CronometerError):
    """A non-2xx API response not covered by a more specific type."""

    error_type = ErrorType.API


class NetworkError(CronometerError):
    """The request never got a response (DNS/timeout/connection)."""

    error_type = ErrorType.NETWORK


def error_for_status(status: int, body: str) -> CronometerError:
    """Map an HTTP status + body to the most specific :class:`CronometerError`."""
    message = f"Cronometer API returned {status}: {body}"
    if status in (401, 403):
        return AuthenticationError(message, status=status, body=body)
    if status == 404:
        return NotFoundError(message, status=status, body=body)
    if status == 429:
        return RateLimitError(message, status=status, body=body)
    return ApiError(message, status=status, body=body)
