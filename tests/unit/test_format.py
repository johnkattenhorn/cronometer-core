"""Tests for cronometer_core.format.to_text auto-detection."""
from __future__ import annotations

import json

from cronometer_core.format import to_text


def test_daily_nutrition():
    data = [
        {
            "date": "2026-07-20",
            "energy_kcal": 2000,
            "protein_g": 150,
            "carbs_g": 180,
            "fat_g": 70,
            "fiber_g": 30,
        }
    ]
    out = to_text(data)
    assert "Daily nutrition (1 day(s))" in out
    assert "2000 kcal" in out
    assert "P 150g" in out


def test_servings():
    data = [
        {
            "day": "2026-07-20",
            "time": "08:00",
            "food_name": "Eggs",
            "amount": 2,
            "unit": "large",
            "energy_kcal": 140,
            "protein_g": 12,
        }
    ]
    out = to_text(data)
    assert "Servings (1)" in out
    assert "Eggs" in out


def test_protein_status():
    data = {
        "date": "2026-07-20",
        "target": 150,
        "consumed": 120,
        "remaining": 30,
        "percentage": 80,
        "status": "on_track",
        "message": "Good progress",
    }
    out = to_text(data)
    assert "Protein status" in out
    assert "on_track" in out
    assert "Good progress" in out


def test_weekly_summary():
    data = {
        "start_date": "2026-07-13",
        "end_date": "2026-07-20",
        "days_tracked": 2,
        "averages": {
            "energy_kcal": 2100, "protein_g": 155, "carbs_g": 190,
            "fat_g": 75, "fiber_g": 27,
        },
        "totals": {
            "energy_kcal": 4200, "protein_g": 310, "carbs_g": 380,
            "fat_g": 150, "fiber_g": 55,
        },
        "daily_data": [],
    }
    out = to_text(data)
    assert "Weekly summary" in out
    assert "2 day(s) tracked" in out
    assert "4200 kcal" in out


def test_biometrics():
    data = [
        {"day": "2026-07-20", "time": "07:00", "metric": "Weight", "unit": "kg", "amount": 82.4}
    ]
    out = to_text(data)
    assert "Biometrics (1)" in out
    assert "Weight" in out
    assert "82.4" in out


def test_exercises():
    data = [
        {
            "day": "2026-07-20", "time": "18:00", "exercise": "Run",
            "minutes": 30, "calories_burned": 300,
        }
    ]
    out = to_text(data)
    assert "Exercises (1)" in out
    assert "Run" in out


def test_notes():
    data = [{"day": "2026-07-20", "note": "Felt great"}]
    out = to_text(data)
    assert "Notes (1)" in out
    assert "Felt great" in out


def test_targets():
    data = {
        "protein": {"id": 203, "min": 150, "max": 150, "custom": False},
        "fat": {"id": 204, "min": 70, "max": 70, "custom": False},
        "carbs": {"id": -1205, "min": 180, "max": 180, "custom": True},
        "energy": {"id": 208, "min": 2000, "max": 2000, "custom": False},
        "fiber": {"id": 291, "min": 30, "max": 30, "custom": False},
        "all": [],
    }
    out = to_text(data)
    assert "Nutrient targets" in out
    assert "Protein (g): 150" in out
    assert "(custom)" in out


def test_empty_list():
    assert to_text([]) == "(none)"


def test_none_and_scalar():
    assert to_text(None) == "(no content)"
    assert to_text(42) == "42"


def test_unknown_dict_falls_back_to_json():
    data = {"totally": "unknown"}
    assert json.loads(to_text(data)) == data
