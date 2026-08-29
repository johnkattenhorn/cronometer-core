"""Declarative operation registry — the contract both adapters generate from.

``OPERATIONS`` lists every Cronometer operation once: its name, the underlying
:mod:`cronometer_core.operations` function, help text, read/write flag, and
typed parameters. The ``click`` CLI (:mod:`cronometer_core.cli`) and the FastMCP
server (:mod:`cronometer_core.mcp_server`) are both *generated* from this list,
so a change here updates both surfaces identically — the MCP stays a 1:1 wrapper
of the CLI switches by construction.

All eight operations are read-only.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from . import operations as ops

# Parameter kinds understood by the adapters.
INT = "int"
STR = "str"
BOOL = "bool"
EXERCISES = "exercises"  # unused here; kept so the generic adapters stay generic


@dataclass(frozen=True)
class Param:
    """One logical parameter of an operation.

    ``name`` is the keyword passed to the operations function. ``cli_flags`` are
    the ``click`` option flags (e.g. ``("--metric",)``); when empty the adapter
    derives ``--<name-with-dashes>``. ``exercises_model`` names the pydantic item
    model for an ``EXERCISES`` param (unused by cronometer).
    """

    name: str
    kind: str
    required: bool = False
    default: Any = None
    help: str = ""
    cli_flags: tuple[str, ...] = ()
    exercises_model: type | None = None


@dataclass(frozen=True)
class Op:
    """One operation, exposed as a CLI subcommand and an MCP tool."""

    name: str
    func: Callable[..., Any]
    help: str
    write: bool = False
    formatted: bool = False
    params: list[Param] = field(default_factory=list)


def _date() -> Param:
    return Param("date", STR, help="Single date YYYY-MM-DD (defaults to today).")


def _start_date(help: str) -> Param:
    return Param("start_date", STR, help=help, cli_flags=("--start-date",))


def _end_date(help: str) -> Param:
    return Param("end_date", STR, help=help, cli_flags=("--end-date",))


OPERATIONS: list[Op] = [
    Op(
        "get-daily-nutrition",
        ops.get_daily_nutrition,
        "Nutrition summary for a date or date range. READ.",
        formatted=True,
        params=[
            _date(),
            _start_date("Start of range YYYY-MM-DD (use with --end-date)."),
            _end_date("End of range YYYY-MM-DD (use with --start-date)."),
        ],
    ),
    Op(
        "get-servings",
        ops.get_servings,
        "Individual food entries for a specific date. READ.",
        formatted=True,
        params=[_date()],
    ),
    Op(
        "get-protein-status",
        ops.get_protein_status,
        "Quick check on today's protein progress vs target. READ.",
        formatted=True,
        params=[],
    ),
    Op(
        "get-weekly-summary",
        ops.get_weekly_summary,
        "Weekly average + total nutrition. READ.",
        formatted=True,
        params=[
            Param(
                "weeks_back",
                INT,
                default=1,
                help="Number of weeks to look back (default 1).",
                cli_flags=("--weeks-back",),
            )
        ],
    ),
    Op(
        "get-biometrics",
        ops.get_biometrics,
        "Weight & biometric entries (optional metric filter). READ.",
        formatted=True,
        params=[
            _start_date("Start date YYYY-MM-DD (defaults to 30 days ago)."),
            _end_date("End date YYYY-MM-DD (defaults to today)."),
            Param(
                "metric",
                STR,
                help="Filter by metric name substring (e.g. 'Weight', 'Body Fat').",
            ),
        ],
    ),
    Op(
        "get-exercises",
        ops.get_exercises,
        "Exercise entries over a date range. READ.",
        formatted=True,
        params=[
            _start_date("Start date YYYY-MM-DD (defaults to 30 days ago)."),
            _end_date("End date YYYY-MM-DD (defaults to today)."),
        ],
    ),
    Op(
        "get-notes",
        ops.get_notes,
        "Daily notes over a date range. READ.",
        formatted=True,
        params=[
            _start_date("Start date YYYY-MM-DD (defaults to 30 days ago)."),
            _end_date("End date YYYY-MM-DD (defaults to today)."),
        ],
    ),
    Op(
        "get-targets",
        ops.get_targets,
        "Configured nutrient targets (protein, fat, carbs, energy, fiber). READ.",
        formatted=True,
        params=[],
    ),
]

# Name -> Op index for adapters/tests.
OPERATIONS_BY_NAME: dict[str, Op] = {op.name: op for op in OPERATIONS}
