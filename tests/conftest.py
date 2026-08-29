"""Shared pytest fixtures for the cronometer-core test suite."""
from __future__ import annotations

import time

import pytest

from cronometer_core.auth import PasswordSessionAuth
from cronometer_core.client import CronometerClient
from cronometer_core.config import Config

BASE_URL = "https://cronometer.com"


def make_logged_in_auth(
    *, base_url: str = BASE_URL, user_id: str = "12345", token: str = "tok-abc"
) -> PasswordSessionAuth:
    """A PasswordSessionAuth with a pre-seeded valid session (no HTTP login).

    Lets operation/client tests exercise the export/targets paths without
    mocking the whole GWT-RPC login handshake.
    """
    auth = PasswordSessionAuth("user@example.com", "pw", base_url=base_url)
    auth._state = {
        "nonce": "sess-nonce",
        "userId": user_id,
        "authToken": token,
        "tokenExpiry": (time.time() + 3600) * 1000.0,
    }
    return auth


@pytest.fixture
def config() -> Config:
    """A fixed test Config (no environment involved)."""
    return Config(username="user@example.com", password="pw", base_url=BASE_URL)


@pytest.fixture
def auth() -> PasswordSessionAuth:
    return make_logged_in_auth()


@pytest.fixture
def client(config: Config, auth: PasswordSessionAuth) -> CronometerClient:
    """A CronometerClient wired to a logged-in auth with a no-op sleep."""
    return CronometerClient(
        config,
        auth=auth,
        session=auth.session,
        max_retries=0,
        backoff=0.0,
        sleep=lambda _: None,
    )
