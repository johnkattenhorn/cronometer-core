"""``click`` CLI generated from :data:`cronometer_core.spec.OPERATIONS`.

One subcommand per operation, built automatically from the shared spec so the
CLI and the MCP server expose an identical surface. Output is normalised JSON by
default; ``--text`` renders the human-readable view. Errors go to stderr as
``{"ok": false, "error": ...}`` with a non-zero exit code.
"""
from __future__ import annotations

import json
import sys
from typing import Any

import click

from .client import CronometerClient
from .config import resolve_auth, resolve_config
from .errors import CronometerError, ValidationError
from .format import to_text
from .spec import BOOL, EXERCISES, INT, OPERATIONS, Op, Param


def _load_exercises(exercises: str | None, exercises_file: str | None) -> list:
    """Resolve an exercises array from inline JSON or a file (CLI convenience)."""
    raw = exercises
    if exercises_file:
        with open(exercises_file, encoding="utf-8") as fh:
            raw = fh.read()
    if not raw:
        raise ValidationError(
            "Provide exercises via --exercises '<json>' or --exercises-file "
            "<path>. It must be a JSON array."
        )
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"exercises is not valid JSON: {exc}") from exc
    if not isinstance(parsed, list):
        raise ValidationError("exercises must be a JSON array.")
    return parsed


def _client(ctx: click.Context) -> CronometerClient:
    obj = ctx.obj or {}
    config = resolve_config(obj.get("username"), obj.get("password"), obj.get("base_url"))
    auth = resolve_auth(config)
    return CronometerClient(config, auth=auth, session=auth.session)


def _emit(ctx: click.Context, result: Any) -> None:
    if (ctx.obj or {}).get("text"):
        click.echo(to_text(result))
    else:
        click.echo(json.dumps(result, indent=2))


def _fail(err: Exception) -> None:
    if isinstance(err, CronometerError):
        payload: dict[str, Any] = err.to_dict()
    else:
        payload = {"ok": False, "error": str(err)}
    click.echo(json.dumps(payload), err=True)
    sys.exit(1)


def _resolve_kwargs(op: Op, raw: dict[str, Any]) -> dict[str, Any]:
    call_kwargs: dict[str, Any] = {}
    for param in op.params:
        if param.kind == EXERCISES:
            call_kwargs["exercises"] = _load_exercises(
                raw.get("exercises"), raw.get("exercises_file")
            )
        else:
            call_kwargs[param.name] = raw.get(param.name)
    return call_kwargs


def _make_options(param: Param) -> list[click.Option]:
    if param.kind == EXERCISES:
        return [
            click.Option(
                ["--exercises", "exercises"],
                default=None,
                help="Exercises as an inline JSON array.",
            ),
            click.Option(
                ["--exercises-file", "exercises_file"],
                default=None,
                type=click.Path(exists=True, dir_okay=False),
                help="Path to a JSON file with the exercises array.",
            ),
        ]
    flags = list(param.cli_flags) or [f"--{param.name.replace('_', '-')}"]
    decls = [*flags, param.name]
    if param.kind == BOOL:
        return [
            click.Option(decls, is_flag=True, default=bool(param.default), help=param.help)
        ]
    click_type = int if param.kind == INT else str
    kwargs: dict[str, Any] = {
        "required": param.required,
        "type": click_type,
        "help": param.help,
    }
    # Passing an explicit ``default`` (even ``None``) makes click treat the
    # option as having a default and silently skips its ``required`` check, so
    # only set a default for optional params.
    if not param.required:
        kwargs["default"] = param.default
    return [click.Option(decls, **kwargs)]


def _make_command(op: Op) -> click.Command:
    def callback(**raw: Any) -> None:
        ctx = click.get_current_context()
        try:
            client = _client(ctx)
            result = op.func(client, **_resolve_kwargs(op, raw))
        except Exception as exc:
            _fail(exc)
        else:
            _emit(ctx, result)

    params: list[click.Parameter] = []
    for param in op.params:
        params.extend(_make_options(param))
    return click.Command(name=op.name, callback=callback, params=params, help=op.help)


@click.group(
    help="Read-only Cronometer nutrition & biometric data CLI (daily nutrition, "
    "servings, protein status, weekly summary, biometrics, exercises, notes, "
    "targets). Shares a core with the Cronometer MCP server."
)
@click.option("--text", "output_text", is_flag=True, help="Human-readable output.")
@click.option("--json", "output_json", is_flag=True, help="Raw JSON output (default).")
@click.option("--username", default=None, help="Override CRONOMETER_USERNAME.")
@click.option("--password", default=None, help="Override CRONOMETER_PASSWORD.")
@click.option("--base-url", default=None, help="Override CRONOMETER_BASE_URL.")
@click.pass_context
def cli(
    ctx: click.Context,
    output_text: bool,
    output_json: bool,
    username: str | None,
    password: str | None,
    base_url: str | None,
) -> None:
    ctx.obj = {
        "text": output_text and not output_json,
        "username": username,
        "password": password,
        "base_url": base_url,
    }


for _op in OPERATIONS:
    cli.add_command(_make_command(_op))


if __name__ == "__main__":
    cli()
