"""Tests for cronometer_core.config — resolve_config and resolve_auth."""
from __future__ import annotations

import pytest

from cronometer_core.auth import PasswordSessionAuth
from cronometer_core.config import (
    DEFAULT_BASE_URL,
    MISSING_CREDS_MESSAGE,
    resolve_auth,
    resolve_config,
)


# --- resolve_config -------------------------------------------------------
def test_explicit_args_beat_env():
    env = {
        "CRONOMETER_USERNAME": "env-user",
        "CRONOMETER_PASSWORD": "env-pw",
        "CRONOMETER_BASE_URL": "https://env.example.com",
    }
    cfg = resolve_config("x-user", "x-pw", "https://explicit.example.com", env=env)
    assert cfg.username == "x-user"
    assert cfg.password == "x-pw"
    assert cfg.base_url == "https://explicit.example.com"


def test_env_used_when_no_explicit_args():
    env = {"CRONOMETER_USERNAME": "env-user", "CRONOMETER_PASSWORD": "env-pw"}
    cfg = resolve_config(env=env)
    assert cfg.username == "env-user"
    assert cfg.password == "env-pw"
    assert cfg.base_url == DEFAULT_BASE_URL


def test_missing_creds_do_not_raise_in_resolve_config():
    cfg = resolve_config(env={})
    assert cfg.username is None
    assert cfg.password is None
    assert cfg.base_url == DEFAULT_BASE_URL


def test_base_url_default():
    cfg = resolve_config("u", "p", env={})
    assert cfg.base_url == DEFAULT_BASE_URL


def test_base_url_trailing_slash_stripped():
    cfg = resolve_config("u", "p", "https://cronometer.com/", env={})
    assert cfg.base_url == "https://cronometer.com"


def test_creds_whitespace_stripped():
    cfg = resolve_config("  spacey  ", "  pw  ", env={})
    assert cfg.username == "spacey"
    assert cfg.password == "pw"


def test_blank_creds_treated_as_missing():
    cfg = resolve_config(env={"CRONOMETER_USERNAME": "   ", "CRONOMETER_PASSWORD": ""})
    assert cfg.username is None
    assert cfg.password is None


# --- resolve_auth ---------------------------------------------------------
def test_resolve_auth_from_env_returns_provider():
    env = {"CRONOMETER_USERNAME": "u", "CRONOMETER_PASSWORD": "p"}
    auth = resolve_auth(env=env)
    assert isinstance(auth, PasswordSessionAuth)
    assert auth.username == "u"
    assert auth.password == "p"
    assert auth.base_url == DEFAULT_BASE_URL


def test_resolve_auth_from_config():
    cfg = resolve_config("cu", "cp", "https://cronometer.com", env={})
    auth = resolve_auth(cfg)
    assert isinstance(auth, PasswordSessionAuth)
    assert auth.username == "cu"
    assert auth.base_url == "https://cronometer.com"


def test_resolve_auth_missing_username_exits_2(capsys):
    with pytest.raises(SystemExit) as exc:
        resolve_auth(env={"CRONOMETER_PASSWORD": "p"})
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert err == MISSING_CREDS_MESSAGE
    assert "CRONOMETER_USERNAME and CRONOMETER_PASSWORD must be set" in err


def test_resolve_auth_missing_password_exits_2(capsys):
    with pytest.raises(SystemExit) as exc:
        resolve_auth(env={"CRONOMETER_USERNAME": "u"})
    assert exc.value.code == 2
    assert capsys.readouterr().err == MISSING_CREDS_MESSAGE


def test_resolve_auth_missing_both_exits_2():
    with pytest.raises(SystemExit) as exc:
        resolve_auth(env={})
    assert exc.value.code == 2
