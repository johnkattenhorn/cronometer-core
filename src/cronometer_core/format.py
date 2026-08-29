"""Human-readable rendering of Cronometer responses.

The original skill emitted JSON only; this adds an opt-in text view used by the
CLI ``--text`` flag and the MCP ``text=true`` option. Normalised JSON remains
the default everywhere.

``to_text`` auto-detects the response shape (the parsed dict/list an operation
returns), so a single entry point serves every operation and falls back to
pretty JSON for anything it doesn't model.
"""
from __future__ import annotations

import json
from typing import Any

Json = Any


def to_text(data: Json) -> str:
    """Render a Cronometer operation result as human-readable text."""
    if data is None:
        return "(no content)"
    if isinstance(data, (int, float, str)):
        return str(data)

    if isinstance(data, dict):
        # Protein status.
        if "status" in data and "consumed" in data and "message" in data:
            return _protein_status(data)
        # Weekly summary.
        if "days_tracked" in data and "averages" in data:
            return _weekly_summary(data)
        # Targets.
        if "all" in data and "protein" in data:
            return _targets(data)
        return json.dumps(data, indent=2)

    if isinstance(data, list):
        if not data:
            return "(none)"
        first = data[0] if isinstance(data[0], dict) else {}
        if "note" in first:
            return _notes(data)
        if "exercise" in first:
            return _exercises(data)
        if "metric" in first:
            return _biometrics(data)
        if "food_name" in first:
            return _servings(data)
        if "energy_kcal" in first and "date" in first:
            return _daily_nutrition(data)
        return json.dumps(data, indent=2)

    return json.dumps(data, indent=2)


def _num(value: Any) -> str:
    if isinstance(value, float) and not value.is_integer():
        return f"{value:.1f}"
    return str(value)


def _daily_nutrition(rows: list[dict]) -> str:
    lines = [f"Daily nutrition ({len(rows)} day(s))"]
    for r in rows:
        lines.append(
            f"  {r.get('date', '?')}: {_num(r.get('energy_kcal', 0))} kcal, "
            f"P {_num(r.get('protein_g', 0))}g / C {_num(r.get('carbs_g', 0))}g / "
            f"F {_num(r.get('fat_g', 0))}g, fiber {_num(r.get('fiber_g', 0))}g"
        )
    return "\n".join(lines)


def _servings(rows: list[dict]) -> str:
    lines = [f"Servings ({len(rows)})"]
    for r in rows:
        amount = _num(r.get("amount", 0))
        unit = r.get("unit", "")
        qty = f"{amount} {unit}".strip()
        lines.append(
            f"  {r.get('time', '')} {r.get('food_name', '?')} — {qty}, "
            f"{_num(r.get('energy_kcal', 0))} kcal, P {_num(r.get('protein_g', 0))}g".strip()
        )
    return "\n".join(lines)


def _protein_status(d: dict) -> str:
    return "\n".join(
        [
            f"Protein status ({d.get('date', '?')}) — {d.get('status', '?')}",
            f"  {_num(d.get('consumed', 0))}g of {_num(d.get('target', 0))}g "
            f"({_num(d.get('percentage', 0))}%), {_num(d.get('remaining', 0))}g remaining",
            f"  {d.get('message', '')}",
        ]
    )


def _weekly_summary(d: dict) -> str:
    avg = d.get("averages") or {}
    tot = d.get("totals") or {}
    return "\n".join(
        [
            f"Weekly summary {d.get('start_date', '?')} → {d.get('end_date', '?')} "
            f"({d.get('days_tracked', 0)} day(s) tracked)",
            f"  avg/day: {_num(avg.get('energy_kcal', 0))} kcal, "
            f"P {_num(avg.get('protein_g', 0))}g / C {_num(avg.get('carbs_g', 0))}g / "
            f"F {_num(avg.get('fat_g', 0))}g, fiber {_num(avg.get('fiber_g', 0))}g",
            f"  totals: {_num(tot.get('energy_kcal', 0))} kcal, "
            f"P {_num(tot.get('protein_g', 0))}g / C {_num(tot.get('carbs_g', 0))}g / "
            f"F {_num(tot.get('fat_g', 0))}g, fiber {_num(tot.get('fiber_g', 0))}g",
        ]
    )


def _biometrics(rows: list[dict]) -> str:
    lines = [f"Biometrics ({len(rows)})"]
    for r in rows:
        unit = r.get("unit", "")
        lines.append(
            f"  {r.get('day', '')} {r.get('metric', '?')}: "
            f"{_num(r.get('amount', 0))} {unit}".rstrip()
        )
    return "\n".join(lines)


def _exercises(rows: list[dict]) -> str:
    lines = [f"Exercises ({len(rows)})"]
    for r in rows:
        lines.append(
            f"  {r.get('day', '')} {r.get('exercise', '?')} — "
            f"{_num(r.get('minutes', 0))} min, {_num(r.get('calories_burned', 0))} kcal"
        )
    return "\n".join(lines)


def _notes(rows: list[dict]) -> str:
    lines = [f"Notes ({len(rows)})"]
    for r in rows:
        lines.append(f"  {r.get('day', '')}: {r.get('note', '')}".rstrip())
    return "\n".join(lines)


def _targets(d: dict) -> str:
    def line(label: str, target: dict | None) -> str:
        if not target:
            return f"  {label}: (not set)"
        lo = target.get("min")
        hi = target.get("max")
        rng = _num(lo) if lo == hi else f"{_num(lo)}-{_num(hi)}"
        custom = " (custom)" if target.get("custom") else ""
        return f"  {label}: {rng}{custom}"

    return "\n".join(
        [
            "Nutrient targets",
            line("Energy (kcal)", d.get("energy")),
            line("Protein (g)", d.get("protein")),
            line("Carbs (g)", d.get("carbs")),
            line("Fat (g)", d.get("fat")),
            line("Fiber (g)", d.get("fiber")),
        ]
    )
