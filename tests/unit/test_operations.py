"""Tests for cronometer_core.operations — export/targets paths (HTTP mocked)."""
from __future__ import annotations

import time

import pytest
import responses

from cronometer_core import operations as ops
from cronometer_core.errors import ApiError, ValidationError

BASE = "https://cronometer.com"
EXPORT = f"{BASE}/export"
TARGETS = f"{BASE}/api/v3/user/12345/targets"

DAILY_CSV = (
    "Date,Energy (kcal),Protein (g),Carbs (g),Fat (g),Fiber (g)\n"
    "2026-07-20,2000,150,180,70,30\n"
)
MULTI_DAY_CSV = (
    "Date,Energy (kcal),Protein (g),Carbs (g),Fat (g),Fiber (g)\n"
    "2026-07-19,2000,150,180,70,30\n"
    "2026-07-20,2200,160,200,80,25\n"
)


# --- date helpers ---------------------------------------------------------
def test_parse_date_invalid_raises():
    with pytest.raises(ValidationError):
        ops.parse_date("2026/07/20", "2026-07-20")


def test_parse_date_default_when_empty():
    assert ops.parse_date(None, "2026-07-20") == "2026-07-20"


def test_is_valid_date():
    assert ops.is_valid_date("2026-07-20") is True
    assert ops.is_valid_date("2026-13-01") is False
    assert ops.is_valid_date("nope") is False


# --- exports --------------------------------------------------------------
@responses.activate
def test_get_daily_nutrition_parses_and_normalizes(client):
    responses.add(responses.GET, EXPORT, body=DAILY_CSV, status=200)
    out = ops.get_daily_nutrition(client, date="2026-07-20")
    assert out[0]["date"] == "2026-07-20"
    assert out[0]["energy_kcal"] == 2000
    assert isinstance(out[0]["energy_kcal"], int)  # normalized
    # The auth token was sent as the ?nonce= param.
    assert "nonce=tok-abc" in responses.calls[0].request.url
    assert "generate=dailySummary" in responses.calls[0].request.url


@responses.activate
def test_get_daily_nutrition_range(client):
    responses.add(responses.GET, EXPORT, body=MULTI_DAY_CSV, status=200)
    out = ops.get_daily_nutrition(
        client, start_date="2026-07-19", end_date="2026-07-20"
    )
    assert len(out) == 2
    assert "start=2026-07-19" in responses.calls[0].request.url
    assert "end=2026-07-20" in responses.calls[0].request.url


@responses.activate
def test_get_servings(client):
    csv = (
        "Day,Time,Food Name,Amount,Unit,Energy (kcal),Protein (g)\n"
        "2026-07-20,08:00,Eggs,2,large,140,12\n"
    )
    responses.add(responses.GET, EXPORT, body=csv, status=200)
    out = ops.get_servings(client, date="2026-07-20")
    assert out[0]["food_name"] == "Eggs"
    assert "generate=servings" in responses.calls[0].request.url


@responses.activate
def test_get_exercises(client):
    csv = "Day,Time,Exercise,Minutes,Calories Burned\n2026-07-20,18:00,Run,30,300\n"
    responses.add(responses.GET, EXPORT, body=csv, status=200)
    out = ops.get_exercises(client)
    assert out[0]["exercise"] == "Run"
    assert "generate=exercises" in responses.calls[0].request.url


@responses.activate
def test_get_notes(client):
    csv = "Day,Note\n2026-07-20,Good day\n"
    responses.add(responses.GET, EXPORT, body=csv, status=200)
    out = ops.get_notes(client)
    assert out[0]["note"] == "Good day"
    assert "generate=notes" in responses.calls[0].request.url


@responses.activate
def test_get_biometrics_metric_filter(client):
    csv = (
        "Day,Time,Metric,Unit,Amount\n"
        "2026-07-20,07:00,Weight,kg,82\n"
        "2026-07-20,07:00,Body Fat,%,18\n"
    )
    responses.add(responses.GET, EXPORT, body=csv, status=200)
    out = ops.get_biometrics(client, metric="weight")
    assert len(out) == 1
    assert out[0]["metric"] == "Weight"


@responses.activate
def test_get_biometrics_no_filter_returns_all(client):
    csv = (
        "Day,Time,Metric,Unit,Amount\n"
        "2026-07-20,07:00,Weight,kg,82\n"
        "2026-07-20,07:00,Body Fat,%,18\n"
    )
    responses.add(responses.GET, EXPORT, body=csv, status=200)
    out = ops.get_biometrics(client)
    assert len(out) == 2


# --- targets --------------------------------------------------------------
@responses.activate
def test_get_targets_prefers_carbs_fixed(client):
    data = [
        {"id": 203, "min": 150, "max": 150, "custom": False},   # protein
        {"id": 204, "min": 70, "max": 70, "custom": False},     # fat
        {"id": 205, "min": 999, "max": 999, "custom": False},   # carbs (calculated)
        {"id": -1205, "min": 180, "max": 180, "custom": False}, # carbs fixed
        {"id": 208, "min": 2000, "max": 2000, "custom": False}, # energy
        {"id": 291, "min": 30, "max": 30, "custom": False},     # fiber
    ]
    responses.add(responses.GET, TARGETS, json=data, status=200)
    out = ops.get_targets(client)
    assert out["carbs"]["id"] == -1205
    assert out["carbs"]["min"] == 180
    assert out["energy"]["min"] == 2000
    assert out["all"] == data


@responses.activate
def test_get_targets_derives_fixed_energy(client):
    data = [
        {"id": 203, "min": 150, "max": 150, "custom": True},
        {"id": 204, "min": 70, "max": 70, "custom": True},
        {"id": -1205, "min": 180, "max": 180, "custom": True},
        {"id": 291, "min": 30, "max": 30, "custom": True},
    ]
    responses.add(responses.GET, TARGETS, json=data, status=200)
    out = ops.get_targets(client)
    # 150*4 + 180*4 + 70*9 = 600 + 720 + 630 = 1950
    assert out["energy"]["min"] == 1950
    assert out["energy"]["max"] == 1950
    assert out["energy"]["custom"] is True


# --- composites -----------------------------------------------------------
@responses.activate
def test_get_protein_status_on_track(client):
    targets = [{"id": 203, "min": 150, "max": 150, "custom": False}]
    responses.add(responses.GET, TARGETS, json=targets, status=200)
    responses.add(responses.GET, EXPORT, body=DAILY_CSV, status=200)
    out = ops.get_protein_status(client)
    assert out["target"] == 150
    assert out["consumed"] == 150
    assert out["percentage"] == 100
    assert out["status"] == "on_track"


@responses.activate
def test_get_protein_status_no_data(client):
    targets = [{"id": 203, "min": 150, "max": 150, "custom": False}]
    responses.add(responses.GET, TARGETS, json=targets, status=200)
    responses.add(
        responses.GET, EXPORT, body="Date,Protein (g)\n", status=200
    )  # header only -> no rows
    out = ops.get_protein_status(client)
    assert out["consumed"] == 0
    assert out["status"] == "critical"
    assert out["remaining"] == 150


@responses.activate
def test_get_weekly_summary(client):
    responses.add(responses.GET, EXPORT, body=MULTI_DAY_CSV, status=200)
    out = ops.get_weekly_summary(client, weeks_back=1)
    assert out["days_tracked"] == 2
    assert out["totals"]["energy_kcal"] == 4200
    assert out["averages"]["energy_kcal"] == 2100
    assert len(out["daily_data"]) == 2


@responses.activate
def test_get_weekly_summary_no_data(client):
    responses.add(responses.GET, EXPORT, body="Date,Energy (kcal)\n", status=200)
    out = ops.get_weekly_summary(client)
    assert out["days_tracked"] == 0
    assert out["totals"]["energy_kcal"] == 0
    assert out["daily_data"] == []


# --- export 500 self-heal -------------------------------------------------
@responses.activate
def test_export_500_young_session_raises_server_issue(client):
    # Fresh session (age ~0) -> a 500 is treated as a real server-side issue.
    responses.add(responses.GET, EXPORT, body="boom", status=500)
    with pytest.raises(ApiError) as exc:
        ops.get_daily_nutrition(client, date="2026-07-20")
    assert "server-side issue" in str(exc.value)


@responses.activate
def test_export_500_old_session_reauths_and_retries(client, monkeypatch):
    # Age the session past 5 minutes so the self-heal re-auths instead of raising.
    client.auth._state["tokenExpiry"] = (time.time() + 3000) * 1000.0

    reauthed = {"count": 0}

    def fake_reauth():
        reauthed["count"] += 1
        client.auth._state = {
            "nonce": "n2",
            "userId": "12345",
            "authToken": "tok-2",
            "tokenExpiry": (time.time() + 3600) * 1000.0,
        }

    monkeypatch.setattr(client.auth, "reauth", fake_reauth)

    responses.add(responses.GET, EXPORT, body="boom", status=500)
    responses.add(responses.GET, EXPORT, body=DAILY_CSV, status=200)

    out = ops.get_daily_nutrition(client, date="2026-07-20")
    assert reauthed["count"] == 1
    assert out[0]["energy_kcal"] == 2000
