"""Tests for cronometer_core.models — CSV parsers, helpers, number normalisation."""
from __future__ import annotations

from cronometer_core.models import (
    NUTRIENT_IDS,
    _looks_numeric,
    _normalize_header,
    _normalized_row,
    _read_csv,
    _to_float,
    normalize_numbers,
    parse_biometrics_csv,
    parse_daily_summary_csv,
    parse_exercises_csv,
    parse_notes_csv,
    parse_servings_csv,
)


# --- helpers --------------------------------------------------------------
def test_to_float_empty_and_none_are_zero():
    assert _to_float("") == 0
    assert _to_float("   ") == 0
    assert _to_float(None) == 0


def test_to_float_non_numeric_is_zero():
    assert _to_float("abc") == 0


def test_to_float_parses_numbers():
    assert _to_float("12.5") == 12.5
    assert _to_float("3") == 3.0


def test_normalize_header():
    assert _normalize_header("Energy (kcal)") == "energy_kcal"
    assert _normalize_header("Protein (g)") == "protein_g"
    assert _normalize_header("  Net Carbs ") == "net_carbs"
    assert _normalize_header("Food Name") == "food_name"


def test_looks_numeric():
    assert _looks_numeric("12") is True
    assert _looks_numeric("12.5") is True
    assert _looks_numeric("") is False
    assert _looks_numeric("abc") is False
    assert _looks_numeric(None) is False


def test_read_csv_trims_and_skips_empty_lines():
    text = "A,B\n 1 , 2 \n\n3,4\n"
    rows = _read_csv(text)
    assert rows == [{"A": "1", "B": "2"}, {"A": "3", "B": "4"}]


def test_normalized_row():
    assert _normalized_row({"Energy (kcal)": "100"}) == {"energy_kcal": "100"}


# --- parse_daily_summary_csv ----------------------------------------------
def test_parse_daily_summary_basic():
    csv_text = (
        "Date,Energy (kcal),Protein (g),Carbs (g),Fat (g),Fiber (g)\n"
        "2026-07-20,2000,150,180,70,30\n"
    )
    out = parse_daily_summary_csv(csv_text)
    assert len(out) == 1
    r = out[0]
    assert r["date"] == "2026-07-20"
    assert r["energy_kcal"] == 2000
    assert r["protein_g"] == 150
    assert r["carbs_g"] == 180
    assert r["fat_g"] == 70
    assert r["fiber_g"] == 30


def test_parse_daily_summary_header_aliases_and_extra_numeric():
    # "Calories" aliases energy; a stray numeric column is captured too.
    csv_text = "Day,Calories,Protein,Sugars,Potassium (mg)\n2026-07-20,1800,120,50,3000\n"
    out = parse_daily_summary_csv(csv_text)
    r = out[0]
    assert r["date"] == "2026-07-20"
    assert r["energy_kcal"] == 1800
    assert r["protein_g"] == 120
    assert r["sugar_g"] == 50
    # extra numeric column preserved via the passthrough loop
    assert r["potassium_mg"] == 3000


def test_parse_daily_summary_empty():
    assert parse_daily_summary_csv("") == []


# --- parse_servings_csv ---------------------------------------------------
def test_parse_servings_basic_and_passthrough():
    csv_text = (
        "Day,Time,Group,Food Name,Amount,Unit,Energy (kcal),Protein (g),Notes\n"
        "2026-07-20,08:00,Dairy,Greek Yogurt,1,cup,150,20,tasty\n"
    )
    out = parse_servings_csv(csv_text)
    r = out[0]
    assert r["food_name"] == "Greek Yogurt"
    assert r["amount"] == 1
    assert r["unit"] == "cup"
    assert r["energy_kcal"] == 150
    assert r["protein_g"] == 20
    # non-numeric extra column preserved as string
    assert r["notes"] == "tasty"


# --- parse_exercises_csv --------------------------------------------------
def test_parse_exercises():
    csv_text = "Day,Time,Exercise,Minutes,Calories Burned\n2026-07-20,18:00,Running,30,300\n"
    out = parse_exercises_csv(csv_text)
    assert out[0] == {
        "day": "2026-07-20",
        "time": "18:00",
        "exercise": "Running",
        "minutes": 30,
        "calories_burned": 300,
    }


# --- parse_biometrics_csv -------------------------------------------------
def test_parse_biometrics():
    csv_text = "Day,Time,Metric,Unit,Amount\n2026-07-20,07:00,Weight,kg,82.4\n"
    out = parse_biometrics_csv(csv_text)
    assert out[0]["metric"] == "Weight"
    assert out[0]["unit"] == "kg"
    assert out[0]["amount"] == 82.4


# --- parse_notes_csv ------------------------------------------------------
def test_parse_notes_with_aliases():
    csv_text = "Date,Content\n2026-07-20,Felt great today\n"
    out = parse_notes_csv(csv_text)
    assert out[0] == {"day": "2026-07-20", "note": "Felt great today"}


# --- normalize_numbers ----------------------------------------------------
def test_normalize_numbers_integral_floats_become_ints():
    assert normalize_numbers(12.0) == 12
    assert isinstance(normalize_numbers(12.0), int)
    assert normalize_numbers(0.0) == 0


def test_normalize_numbers_keeps_fractional():
    assert normalize_numbers(12.5) == 12.5
    assert isinstance(normalize_numbers(12.5), float)


def test_normalize_numbers_recurses():
    data = {"a": 1.0, "b": [2.0, 3.5, {"c": 4.0}], "d": "x", "e": True}
    out = normalize_numbers(data)
    assert out == {"a": 1, "b": [2, 3.5, {"c": 4}], "d": "x", "e": True}
    assert isinstance(out["a"], int)
    assert isinstance(out["e"], bool)


def test_nutrient_ids_present():
    assert NUTRIENT_IDS["PROTEIN"] == 203
    assert NUTRIENT_IDS["CARBS"] == 205
    assert NUTRIENT_IDS["CARBS_FIXED"] == -1205
    assert NUTRIENT_IDS["ENERGY"] == 208
