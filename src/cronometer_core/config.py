"""Configuration resolution for cronometer-core.

Resolves the Cronometer credentials and base URL from explicit arguments or the
environment. Both the CLI (via the skill's split-config env file) and the MCP
server share this so credential handling is identical everywhere.

Cronometer has **no API key** — auth is your ordinary cronometer.com login.

Environment variables:
  CRONOMETER_USERNAME  required — cronometer.com account username/email
  CRONOMETER_PASSWORD  required — cronometer.com account password
  CRONOMETER_BASE_URL  optional — base URL override (default https://cronometer.com)
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from .auth import PasswordSessionAuth

DEFAULT_BASE_URL = "https://cronometer.com"

ENV_USERNAME = "CRONOMETER_USERNAME"
ENV_PASSWORD = "CRONOMETER_PASSWORD"  # noqa: S105 — env var name, not a secret
ENV_BASE_URL = "CRONOMETER_BASE_URL"

# Exact message the skill wrote before exiting 2 — preserved byte-for-byte.
MISSING_CREDS_MESSAGE = (
    "Error: CRONOMETER_USERNAME and CRONOMETER_PASSWORD must be set "
    "(source ~/.config/claude-skills/cronometer.env).\n"
)


@dataclass(frozen=True)
class Config:
    """Resolved runtime configuration."""

    username: str | None = None
    password: str | None = None
    base_url: str = DEFAULT_BASE_URL


def resolve_config(
    username: str | None = None,
    password: str | None = None,
    base_url: str | None = None,
    *,
    env: dict[str, str] | None = None,
) -> Config:
    """Resolve configuration, preferring explicit args over the environment.

    Unlike a keyed service, this never raises on missing credentials — the
    exit-2 guard lives in :func:`resolve_auth` so it fires only when auth is
    actually constructed (mirroring the skill's ``get_client`` behaviour).
    """
    source = os.environ if env is None else env
    user = (username or source.get(ENV_USERNAME) or "").strip() or None
    pw = (password or source.get(ENV_PASSWORD) or "").strip() or None
    url = (base_url or source.get(ENV_BASE_URL) or DEFAULT_BASE_URL).strip()
    return Config(username=user, password=pw, base_url=url.rstrip("/"))


def resolve_auth(
    config: Config | None = None,
    *,
    env: dict[str, str] | None = None,
) -> PasswordSessionAuth:
    """Build a :class:`PasswordSessionAuth` from a config or the environment.

    If either credential is missing, writes the skill's exact error to stderr
    and exits with code 2 (preserving the CLI's contract without editing the
    generic ``cli.py``).
    """
    source = os.environ if env is None else env
    if config is not None:
        username = config.username
        password = config.password
        base_url = config.base_url
    else:
        username = (source.get(ENV_USERNAME) or "").strip() or None
        password = (source.get(ENV_PASSWORD) or "").strip() or None
        base_url = (source.get(ENV_BASE_URL) or DEFAULT_BASE_URL).strip().rstrip("/")
    if not username or not password:
        sys.stderr.write(MISSING_CREDS_MESSAGE)
        sys.exit(2)
    return PasswordSessionAuth(username, password, base_url=base_url)
