"""Cronometer operations — the single source of truth for all business logic.

Each function is a thin, pure operation over a
:class:`~cronometer_core.client.CronometerClient`: it resolves dates, issues the
export/API request, parses the response, and returns plain dicts/lists with
numbers normalised (integral floats -> ints) so both adapters emit output
identical to the original skill.

Ported from the skill's ``CronometerClient`` methods, preserving behaviour
including the ``/export`` 500 self-heal (``_with_export_retry``).
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any, TypeVar, cast

from .auth import PasswordSessionAuth
from .client import CronometerClient
from .errors import ApiError, AuthenticationError, CronometerError, ValidationError
from .models import (
    NUTRIENT_IDS,
    normalize_numbers,
    parse_biometrics_csv,
    parse_daily_summary_csv,
    parse_exercises_csv,
    parse_notes_csv,
    parse_servings_csv,
)

Json = Any
T = TypeVar("T")


# --- date helpers (replicate export.ts) -------------------------------------
def get_today() -> str:
    return date.today().isoformat()


def get_days_ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def get_weeks_ago(weeks: int) -> str:
    return (date.today() - timedelta(days=weeks * 7)).isoformat()


def is_valid_date(s: str) -> bool:
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return False
    try:
        date.fromisoformat(s)
        return True
    except ValueError:
        return False


def parse_date(date_str: str | None, default_date: str) -> str:
    if not date_str:
        return default_date
    if not is_valid_date(date_str):
        raise ValidationError(
            f"Invalid date format: {date_str}. Use YYYY-MM-DD format."
        )
    return date_str


# --- export plumbing --------------------------------------------------------
def _auth(client: CronometerClient) -> PasswordSessionAuth:
    """Narrow the client's ``AuthProvider`` to the cronometer session provider."""
    auth = client.auth
    if not isinstance(auth, PasswordSessionAuth):
        raise AuthenticationError(
            "CronometerClient requires a PasswordSessionAuth provider."
        )
    return auth


def _export(client: CronometerClient, export_type: str, start: str, end: str) -> str:
    """GET the CSV export. The provider adds ``nonce`` as a query param."""
    result = client.get(
        "/export", {"generate": export_type, "start": start, "end": end}
    )
    return cast(str, result)


def _with_export_retry(
    client: CronometerClient, op: Callable[[], T], retried: bool = False
) -> T:
    """Self-heal an export 500: if the session is older than 5 minutes, force a
    re-login and retry once; if it is fresh, the 500 is a real server-side issue
    (or unsupported export type), so surface it."""
    try:
        return op()
    except CronometerError as error:
        if not retried and getattr(error, "status", None) == 500:
            auth = _auth(client)
            state = auth.session_state
            if state is not None:
                session_age = (time.time() * 1000.0) - (
                    state["tokenExpiry"] - 3600 * 1000
                )
                if session_age < 5 * 60 * 1000:
                    raise ApiError(
                        "Export failed with 500 error. This may indicate a "
                        "server-side issue or unsupported export type. "
                        f"Original: {error.message}",
                        status=500,
                    ) from error
            try:
                auth.reauth()
                return _with_export_retry(client, op, True)
            except CronometerError:
                raise error from None
        raise


# --- operations -------------------------------------------------------------
def get_daily_nutrition(
    client: CronometerClient,
    date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> Json:
    """Nutrition summary for a single date or a date range."""

    def op() -> Json:
        if start_date and end_date:
            s = parse_date(start_date, get_today())
            e = parse_date(end_date, get_today())
        else:
            d = parse_date(date, get_today())
            s = d
            e = d
        csv_text = _export(client, "dailySummary", s, e)
        return normalize_numbers(parse_daily_summary_csv(csv_text))

    return _with_export_retry(client, op)


def get_servings(client: CronometerClient, date: str | None = None) -> Json:
    """Individual food entries for a specific date."""

    def op() -> Json:
        d = parse_date(date, get_today())
        csv_text = _export(client, "servings", d, d)
        return normalize_numbers(parse_servings_csv(csv_text))

    return _with_export_retry(client, op)


def get_exercises(
    client: CronometerClient,
    start_date: str | None = None,
    end_date: str | None = None,
) -> Json:
    """Exercise entries over a date range (defaults to the last 30 days)."""

    def op() -> Json:
        s = parse_date(start_date, get_days_ago(30))
        e = parse_date(end_date, get_today())
        csv_text = _export(client, "exercises", s, e)
        return normalize_numbers(parse_exercises_csv(csv_text))

    return _with_export_retry(client, op)


def get_biometrics(
    client: CronometerClient,
    start_date: str | None = None,
    end_date: str | None = None,
    metric: str | None = None,
) -> Json:
    """Weight & biometric entries, optionally filtered by metric substring."""

    def op() -> Json:
        s = parse_date(start_date, get_days_ago(30))
        e = parse_date(end_date, get_today())
        csv_text = _export(client, "biometrics", s, e)
        records = parse_biometrics_csv(csv_text)
        if metric:
            metric_lower = metric.lower()
            records = [r for r in records if metric_lower in r["metric"].lower()]
        return normalize_numbers(records)

    return _with_export_retry(client, op)


def get_notes(
    client: CronometerClient,
    start_date: str | None = None,
    end_date: str | None = None,
) -> Json:
    """Daily notes over a date range (defaults to the last 30 days)."""

    def op() -> Json:
        s = parse_date(start_date, get_days_ago(30))
        e = parse_date(end_date, get_today())
        csv_text = _export(client, "notes", s, e)
        return normalize_numbers(parse_notes_csv(csv_text))

    return _with_export_retry(client, op)


def get_targets(client: CronometerClient) -> Json:
    """Configured nutrient targets (protein, fat, carbs, energy, fiber)."""

    def op() -> Json:
        user_id = _auth(client).user_id
        data = client.get(f"/api/v3/user/{user_id}/targets")

        def find_target(_id: int) -> dict | None:
            for t in data:
                if t.get("id") == _id:
                    return t
            return None

        carbs_fixed = find_target(NUTRIENT_IDS["CARBS_FIXED"])
        carbs_calculated = find_target(NUTRIENT_IDS["CARBS"])

        protein = find_target(NUTRIENT_IDS["PROTEIN"])
        fat = find_target(NUTRIENT_IDS["FAT"])
        carbs = carbs_fixed if carbs_fixed is not None else carbs_calculated
        energy = find_target(NUTRIENT_IDS["ENERGY"])

        # Fixed Targets (custom macros): API omits fixed energy, so derive it.
        if (
            protein and protein.get("custom")
            and fat and fat.get("custom")
            and carbs and carbs.get("custom")
        ):
            protein_kcal = (protein.get("min") or 0) * 4
            carbs_kcal = (carbs.get("min") or 0) * 4
            fat_kcal = (fat.get("min") or 0) * 9
            calculated_energy = protein_kcal + carbs_kcal + fat_kcal
            energy = {
                "id": NUTRIENT_IDS["ENERGY"],
                "min": calculated_energy,
                "max": calculated_energy,
                "vis": True,
                "custom": True,
            }

        return normalize_numbers(
            {
                "protein": protein,
                "fat": fat,
                "carbs": carbs,
                "energy": energy,
                "fiber": find_target(NUTRIENT_IDS["FIBER"]),
                "all": data,
            }
        )

    return _with_export_retry(client, op)


def get_protein_status(client: CronometerClient) -> Json:
    """Quick check on today's protein progress vs target."""
    today = get_today()
    targets = get_targets(client)
    daily_data = get_daily_nutrition(client, date=today)

    if len(daily_data) == 0:
        protein_target = (targets.get("protein") or {}).get("min")
        if protein_target is None:
            protein_target = 150
        return normalize_numbers(
            {
                "date": today,
                "target": protein_target,
                "consumed": 0,
                "remaining": protein_target,
                "percentage": 0,
                "status": "critical",
                "message": "No data logged for today yet.",
            }
        )

    today_data = daily_data[0]
    consumed = today_data["protein_g"]

    target = (targets.get("protein") or {}).get("min")
    if target is None:
        target = 150

    remaining = max(0, target - consumed)
    percentage = (consumed / target) * 100 if target > 0 else 0

    if percentage >= 100:
        status = "on_track"
        message = f"Target hit! {consumed:.1f}g of {target}g ({percentage:.0f}%)"
    elif percentage >= 80:
        status = "on_track"
        message = f"Good progress: {consumed:.1f}g of {target}g ({percentage:.0f}%)"
    elif percentage >= 60:
        status = "behind"
        message = f"Behind target: {consumed:.1f}g of {target}g — {remaining:.1f}g remaining"
    else:
        status = "critical"
        message = (
            f"Protein critical: Only {consumed:.1f}g of {target}g — "
            f"need {remaining:.1f}g more"
        )

    return normalize_numbers(
        {
            "date": today,
            "target": target,
            "consumed": consumed,
            "remaining": remaining,
            "percentage": percentage,
            "status": status,
            "message": message,
        }
    )


def get_weekly_summary(client: CronometerClient, weeks_back: int | None = None) -> Json:
    """Weekly average + total nutrition over the last ``weeks_back`` weeks."""
    weeks_back = weeks_back if weeks_back is not None else 1
    end_date = get_today()
    start_date = get_weeks_ago(weeks_back)

    daily_data = get_daily_nutrition(client, start_date=start_date, end_date=end_date)
    days_tracked = len(daily_data)

    if days_tracked == 0:
        zero = {"energy_kcal": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0, "fiber_g": 0}
        return normalize_numbers(
            {
                "start_date": start_date,
                "end_date": end_date,
                "days_tracked": 0,
                "averages": dict(zero),
                "totals": dict(zero),
                "daily_data": [],
            }
        )

    totals = {"energy_kcal": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0, "fiber_g": 0}
    for day in daily_data:
        totals["energy_kcal"] += day["energy_kcal"]
        totals["protein_g"] += day["protein_g"]
        totals["carbs_g"] += day["carbs_g"]
        totals["fat_g"] += day["fat_g"]
        totals["fiber_g"] += day["fiber_g"]

    averages = {k: v / days_tracked for k, v in totals.items()}

    return normalize_numbers(
        {
            "start_date": start_date,
            "end_date": end_date,
            "days_tracked": days_tracked,
            "averages": averages,
            "totals": totals,
            "daily_data": daily_data,
        }
    )
