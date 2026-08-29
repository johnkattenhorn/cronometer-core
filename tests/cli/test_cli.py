"""Tests for the click CLI (cronometer_core.cli) — HTTP mocked with `responses`.

Happy-path tests patch ``resolve_auth`` to inject a pre-logged-in session so the
GWT login handshake need not be mocked; only the export/targets calls are.
"""
from __future__ import annotations

import json
import time

import pytest
import responses
from click.testing import CliRunner

from cronometer_core.auth import PasswordSessionAuth
from cronometer_core.cli import cli
from cronometer_core.spec import OPERATIONS

BASE = "https://cronometer.com"
EXPORT = f"{BASE}/export"
TARGETS = f"{BASE}/api/v3/user/12345/targets"
ENV = {"CRONOMETER_USERNAME": "u@example.com", "CRONOMETER_PASSWORD": "pw"}

DAILY_CSV = (
    "Date,Energy (kcal),Protein (g),Carbs (g),Fat (g),Fiber (g)\n"
    "2026-07-20,2000,150,180,70,30\n"
)


def _logged_in_auth() -> PasswordSessionAuth:
    a = PasswordSessionAuth("u@example.com", "pw")
    a._state = {
        "nonce": "n",
        "userId": "12345",
        "authToken": "tok-abc",
        "tokenExpiry": (time.time() + 3600) * 1000.0,
    }
    return a


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture(autouse=True)
def _patch_auth(monkeypatch):
    monkeypatch.setattr("cronometer_core.cli.resolve_auth", lambda config: _logged_in_auth())


def test_all_operations_registered(runner):
    names = set(cli.commands)
    expected = {op.name for op in OPERATIONS}
    assert names == expected
    assert len(expected) == 8


@responses.activate
def test_get_targets_json_output(runner):
    data = [
        {"id": 203, "min": 150, "max": 150, "custom": False},
        {"id": 208, "min": 2000, "max": 2000, "custom": False},
    ]
    responses.add(responses.GET, TARGETS, json=data, status=200)
    result = runner.invoke(cli, ["get-targets"], env=ENV)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["protein"]["min"] == 150
    assert payload["energy"]["min"] == 2000


@responses.activate
def test_get_daily_nutrition_json_output(runner):
    responses.add(responses.GET, EXPORT, body=DAILY_CSV, status=200)
    result = runner.invoke(
        cli, ["get-daily-nutrition", "--date", "2026-07-20"], env=ENV
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload[0]["energy_kcal"] == 2000
    assert payload[0]["date"] == "2026-07-20"


@responses.activate
def test_text_flag_renders_human_text(runner):
    responses.add(responses.GET, EXPORT, body=DAILY_CSV, status=200)
    result = runner.invoke(
        cli, ["--text", "get-daily-nutrition", "--date", "2026-07-20"], env=ENV
    )
    assert result.exit_code == 0, result.output
    assert "Daily nutrition" in result.output
    assert "2000 kcal" in result.output


@responses.activate
def test_biometrics_metric_filter(runner):
    csv = (
        "Day,Time,Metric,Unit,Amount\n"
        "2026-07-20,07:00,Weight,kg,82\n"
        "2026-07-20,07:00,Body Fat,%,18\n"
    )
    responses.add(responses.GET, EXPORT, body=csv, status=200)
    result = runner.invoke(cli, ["get-biometrics", "--metric", "weight"], env=ENV)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert len(payload) == 1
    assert payload[0]["metric"] == "Weight"


def test_missing_creds_exits_2(monkeypatch):
    # Do NOT patch resolve_auth here: exercise the real exit-2 guard.
    monkeypatch.undo()
    runner = CliRunner()
    result = runner.invoke(
        cli, ["get-targets"], env={"CRONOMETER_USERNAME": "", "CRONOMETER_PASSWORD": ""}
    )
    assert result.exit_code == 2
    assert "CRONOMETER_USERNAME and CRONOMETER_PASSWORD must be set" in result.stderr
