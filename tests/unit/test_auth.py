"""Tests for the auth layer (auth.py): token stores + the GWT-RPC login flow."""
from __future__ import annotations

import json
import os
import time

import pytest
import responses

from cronometer_core import auth as auth_mod
from cronometer_core.auth import (
    GWT_VALUES,
    JsonFileTokenStore,
    NullTokenStore,
    PasswordSessionAuth,
    RequestParts,
)
from cronometer_core.errors import AuthenticationError

PERM = "F9A8D0A4A73CE43C69A1EC5994B87F20"
NOCACHE = "https://cronometer.com/cronometer/cronometer.nocache.js"
LOGIN_PAGE = "https://cronometer.com/login/"
LOGIN = "https://cronometer.com/login"
GWT_APP = "https://cronometer.com/cronometer/app"


@pytest.fixture(autouse=True)
def _reset_gwt():
    """Reset the module-global GWT init flag/permutation between tests."""
    auth_mod._gwt_initialized["done"] = False
    original = dict(GWT_VALUES)
    yield
    auth_mod._gwt_initialized["done"] = False
    GWT_VALUES.update(original)


def _add_nocache(perm: str = PERM) -> None:
    responses.add(responses.GET, NOCACHE, body=f"gwt.onPropertyDefined='{perm}';", status=200)


def _add_login_cycle(*, token: str = "THE_TOKEN", user_id: str = "12345") -> None:
    """Register one full login handshake (login page → login → 2x GWT app)."""
    responses.add(
        responses.GET,
        LOGIN_PAGE,
        body='<input name="anticsrf" value="CSRF-1"/>',
        status=200,
    )
    responses.add(
        responses.POST,
        LOGIN,
        body="{}",
        status=200,
        headers={"Set-Cookie": "sesnonce=NONCE-1; Path=/"},
    )
    responses.add(responses.POST, GWT_APP, body=f"//OK[{user_id},[],0,7]", status=200)
    responses.add(responses.POST, GWT_APP, body=f'//OK[1,["{token}"],0,7]', status=200)


# --- token stores ---------------------------------------------------------
def test_null_token_store_is_noop():
    store = NullTokenStore()
    assert store.load() is None
    store.save({"a": 1})
    assert store.load() is None


def test_json_file_token_store_round_trip(tmp_path):
    path = os.path.join(tmp_path, "sub", "tokens.json")
    store = JsonFileTokenStore(path)
    assert store.load() is None
    store.save({"refreshToken": "abc"})
    assert store.load() == {"refreshToken": "abc"}
    store.save({"refreshToken": "def"})
    assert store.load() == {"refreshToken": "def"}


def test_json_file_token_store_load_tolerates_corruption(tmp_path):
    path = os.path.join(tmp_path, "tokens.json")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{not json")
    assert JsonFileTokenStore(path).load() is None


def test_json_file_token_store_is_atomic(tmp_path, monkeypatch):
    path = os.path.join(tmp_path, "tokens.json")
    store = JsonFileTokenStore(path)
    store.save({"v": 1})

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        store.save({"v": 2})
    with open(path, encoding="utf-8") as fh:
        assert json.load(fh) == {"v": 1}
    leftovers = [n for n in os.listdir(tmp_path) if n.startswith(".tokens-")]
    assert leftovers == []


# --- PasswordSessionAuth login handshake ----------------------------------
@responses.activate
def test_full_login_handshake_populates_session():
    _add_nocache()
    _add_login_cycle(token="AUTH-TOKEN-1", user_id="98765")
    a = PasswordSessionAuth("user@example.com", "pw")
    assert a.user_id == "98765"
    assert a.auth_token == "AUTH-TOKEN-1"
    assert a.is_session_valid()
    state = a.session_state
    assert state is not None
    assert state["nonce"] == "NONCE-1"


@responses.activate
def test_prepare_sets_nonce_param_to_auth_token():
    _add_nocache()
    _add_login_cycle(token="TKN")
    a = PasswordSessionAuth("u", "p")
    req = RequestParts()
    a.prepare(req)
    assert req.params["nonce"] == "TKN"


@responses.activate
def test_login_once_and_reuse_within_hour():
    _add_nocache()
    _add_login_cycle()
    a = PasswordSessionAuth("u", "p")
    _ = a.user_id  # triggers login
    calls_after_first = len(responses.calls)
    # Subsequent access reuses the valid session — no new HTTP.
    _ = a.auth_token
    _ = a.user_id
    assert len(responses.calls) == calls_after_first


@responses.activate
def test_relogin_when_token_expired():
    _add_nocache()
    _add_login_cycle(token="FIRST")
    _add_login_cycle(token="SECOND")
    a = PasswordSessionAuth("u", "p")
    assert a.auth_token == "FIRST"
    calls_after_first = len(responses.calls)
    # Expire the session; next access must re-login.
    a._state["tokenExpiry"] = (time.time() - 10) * 1000.0
    assert not a.is_session_valid()
    assert a.auth_token == "SECOND"
    assert len(responses.calls) > calls_after_first


@responses.activate
def test_on_auth_failure_forces_relogin():
    _add_nocache()
    _add_login_cycle(token="FIRST")
    _add_login_cycle(token="SECOND")
    a = PasswordSessionAuth("u", "p")
    assert a.auth_token == "FIRST"
    assert a.on_auth_failure(None) is True
    assert a.auth_token == "SECOND"


@responses.activate
def test_login_no_cookie_raises_auth_error():
    _add_nocache()
    responses.add(
        responses.GET, LOGIN_PAGE, body='<input name="anticsrf" value="C"/>', status=200
    )
    # No Set-Cookie -> no sesnonce -> login failure.
    responses.add(responses.POST, LOGIN, body='{"error": "bad creds"}', status=200)
    a = PasswordSessionAuth("u", "p")
    with pytest.raises(AuthenticationError) as exc:
        _ = a.user_id
    assert "bad creds" in str(exc.value)


@responses.activate
def test_too_many_attempts_raises_rate_limit_message():
    _add_nocache()
    responses.add(
        responses.GET, LOGIN_PAGE, body='<input name="anticsrf" value="C"/>', status=200
    )
    responses.add(responses.POST, LOGIN, body="Too Many Attempts", status=200)
    a = PasswordSessionAuth("u", "p")
    with pytest.raises(AuthenticationError) as exc:
        _ = a.user_id
    assert "Too many login attempts" in str(exc.value)


@responses.activate
def test_gwt_500_triggers_permutation_refetch_and_retry_once():
    # init fetch returns PERM; the refetch after the 500 returns a NEW perm.
    new_perm = "ABCDEF0123456789ABCDEF0123456789"
    _add_nocache(PERM)          # initial ensure_gwt_values_initialized
    _add_nocache(new_perm)      # refetch triggered by the 500
    responses.add(
        responses.GET, LOGIN_PAGE, body='<input name="anticsrf" value="C"/>', status=200
    )
    responses.add(
        responses.POST,
        LOGIN,
        body="{}",
        status=200,
        headers={"Set-Cookie": "sesnonce=N; Path=/"},
    )
    # First GWT authenticate 500s, then (after refetch) succeeds, then token.
    responses.add(responses.POST, GWT_APP, body="error", status=500)
    responses.add(responses.POST, GWT_APP, body="//OK[555,[],0,7]", status=200)
    responses.add(responses.POST, GWT_APP, body='//OK[1,["TK"],0,7]', status=200)

    a = PasswordSessionAuth("u", "p")
    assert a.user_id == "555"
    assert a.auth_token == "TK"
    # The permutation self-healed to the refetched value.
    assert GWT_VALUES["permutation"] == new_perm
