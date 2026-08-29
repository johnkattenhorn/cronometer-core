"""CSV parsers, nutrient IDs, and number normalisation for cronometer-core.

Ported verbatim from the skill's ``cronometer_client.py`` (itself a faithful
port of the TypeScript ``parser.ts``). Cronometer's ``/export`` endpoint returns
CSV; these functions mirror the JS ``csv-parse`` semantics
(``columns:true, skip_empty_lines:true, trim:true``) and header normalisation
exactly, so parsed output matches the old skill byte-for-byte.

Read responses are returned as plain dicts/lists (see ``operations.py``) so no
fidelity is lost.
"""
from __future__ import annotations

import csv
import io
import re
from typing import Any

from .errors import CronometerError, ValidationError

# USDA nutrient IDs (replicate the skill's types.ts NUTRIENT_IDS).
NUTRIENT_IDS = {
    "PROTEIN": 203,
    "FAT": 204,
    "CARBS": 205,            # Net carbs (calculated)
    "CARBS_FIXED": -1205,    # Fixed Targets carbs (user-set)
    "ENERGY": 208,
    "FIBER": 291,
    "SUGAR": 269,
    "SODIUM": 307,
    "CHOLESTEROL": 601,
    "SATURATED_FAT": 606,
    "WATER": 255,
}


# --- parsing helpers (replicate parser.ts) ----------------------------------
def _to_float(value: Any) -> float:
    """parseFloat: empty -> 0, non-numeric -> 0."""
    if value is None or str(value).strip() == "":
        return 0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0


def _normalize_header(header: str) -> str:
    h = header.lower()
    h = re.sub(r"[^a-z0-9]", "_", h)
    h = re.sub(r"_+", "_", h)
    h = re.sub(r"^_|_$", "", h)
    return h


def _looks_numeric(value: Any) -> bool:
    """JS ``!isNaN(Number(value)) && value !== ''`` — whole-string numeric test."""
    if value is None or value == "":
        return False
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _read_csv(csv_text: str) -> list[dict[str, str]]:
    """Mirror csv-parse ``{columns:true, skip_empty_lines:true, trim:true}``."""
    reader = csv.reader(io.StringIO(csv_text))
    rows = [r for r in reader if any((c or "").strip() != "" for c in r)]
    if not rows:
        return []
    header = [(c or "").strip() for c in rows[0]]
    out = []
    for raw in rows[1:]:
        record = {}
        for i, key in enumerate(header):
            val = raw[i].strip() if i < len(raw) else ""
            record[key] = val
        out.append(record)
    return out


def _normalized_row(row: dict[str, str]) -> dict[str, str]:
    return {_normalize_header(k): v for k, v in row.items()}


def parse_daily_summary_csv(csv_text: str) -> list[dict[str, Any]]:
    try:
        records = []
        for row in _read_csv(csv_text):
            n = _normalized_row(row)
            record: dict[str, Any] = {
                "date": n.get("date") or n.get("day") or "",
                "energy_kcal": _to_float(n.get("energy_kcal") or n.get("calories") or "0"),
                "protein_g": _to_float(n.get("protein_g") or n.get("protein") or "0"),
                "carbs_g": _to_float(
                    n.get("carbs_g") or n.get("carbohydrates") or n.get("net_carbs") or "0"
                ),
                "fat_g": _to_float(n.get("fat_g") or n.get("fat") or "0"),
                "fiber_g": _to_float(n.get("fiber_g") or n.get("fiber") or "0"),
                "sugar_g": _to_float(n.get("sugar_g") or n.get("sugars") or "0"),
                "sodium_mg": _to_float(n.get("sodium_mg") or n.get("sodium") or "0"),
                "cholesterol_mg": _to_float(
                    n.get("cholesterol_mg") or n.get("cholesterol") or "0"
                ),
                "saturated_fat_g": _to_float(
                    n.get("saturated_fat_g") or n.get("saturated") or "0"
                ),
            }
            for key, value in n.items():
                if key not in record and value and _looks_numeric(value):
                    record[key] = _to_float(value)
            records.append(record)
        return records
    except CronometerError:
        raise
    except Exception as e:
        raise ValidationError(f"Failed to parse daily summary CSV: {e}") from e


def parse_servings_csv(csv_text: str) -> list[dict[str, Any]]:
    try:
        records = []
        for row in _read_csv(csv_text):
            n = _normalized_row(row)
            record: dict[str, Any] = {
                "day": n.get("day") or n.get("date") or "",
                "time": n.get("time") or "",
                "group": n.get("group") or n.get("food_group") or n.get("category") or "",
                "food_name": n.get("food_name") or n.get("food") or n.get("name") or "",
                "amount": _to_float(n.get("amount") or n.get("quantity") or "0"),
                "unit": n.get("unit") or n.get("serving") or "",
                "energy_kcal": _to_float(n.get("energy_kcal") or n.get("calories") or "0"),
                "protein_g": _to_float(n.get("protein_g") or n.get("protein") or "0"),
                "carbs_g": _to_float(n.get("carbs_g") or n.get("carbohydrates") or "0"),
                "fat_g": _to_float(n.get("fat_g") or n.get("fat") or "0"),
                "fiber_g": _to_float(n.get("fiber_g") or n.get("fiber") or "0"),
            }
            for key, value in n.items():
                if key not in record and value:
                    if _looks_numeric(value):
                        record[key] = _to_float(value)
                    else:
                        record[key] = value
            records.append(record)
        return records
    except CronometerError:
        raise
    except Exception as e:
        raise ValidationError(f"Failed to parse servings CSV: {e}") from e


def parse_exercises_csv(csv_text: str) -> list[dict[str, Any]]:
    try:
        records = []
        for row in _read_csv(csv_text):
            n = _normalized_row(row)
            records.append(
                {
                    "day": n.get("day") or n.get("date") or "",
                    "time": n.get("time") or "",
                    "exercise": n.get("exercise") or n.get("activity") or n.get("name") or "",
                    "minutes": _to_float(n.get("minutes") or n.get("duration") or "0"),
                    "calories_burned": _to_float(
                        n.get("calories_burned") or n.get("calories") or "0"
                    ),
                }
            )
        return records
    except Exception as e:
        raise ValidationError(f"Failed to parse exercises CSV: {e}") from e


def parse_biometrics_csv(csv_text: str) -> list[dict[str, Any]]:
    try:
        records = []
        for row in _read_csv(csv_text):
            n = _normalized_row(row)
            records.append(
                {
                    "day": n.get("day") or n.get("date") or "",
                    "time": n.get("time") or "",
                    "metric": n.get("metric") or n.get("measurement") or n.get("name") or "",
                    "unit": n.get("unit") or "",
                    "amount": _to_float(n.get("amount") or n.get("value") or "0"),
                }
            )
        return records
    except Exception as e:
        raise ValidationError(f"Failed to parse biometrics CSV: {e}") from e


def parse_notes_csv(csv_text: str) -> list[dict[str, Any]]:
    try:
        records = []
        for row in _read_csv(csv_text):
            n = _normalized_row(row)
            records.append(
                {
                    "day": n.get("day") or n.get("date") or "",
                    "note": n.get("note") or n.get("notes") or n.get("content") or "",
                }
            )
        return records
    except Exception as e:
        raise ValidationError(f"Failed to parse notes CSV: {e}") from e


def normalize_numbers(obj: Any) -> Any:
    """Match JS ``JSON.stringify``: integral floats serialize without a ``.0``.

    Recurses dicts/lists, converting any float whose value ``is_integer()`` to an
    ``int`` (e.g. ``12.0`` -> ``12``, ``0.0`` -> ``0``) so the generic ``cli.py``
    ``json.dumps`` output matches the old skill byte-for-byte.
    """
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        if obj.is_integer():
            return int(obj)
        return obj
    if isinstance(obj, dict):
        return {k: normalize_numbers(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [normalize_numbers(v) for v in obj]
    return obj
