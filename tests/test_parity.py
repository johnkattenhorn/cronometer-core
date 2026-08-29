"""Parity guard: CLI commands == MCP tools == spec.OPERATIONS names.

The whole point of the shared spec is that the two adapters can never silently
diverge. This test fails loudly if any name is added/removed from one surface
but not the others.
"""
from __future__ import annotations

from fastmcp import Client

from cronometer_core.cli import cli
from cronometer_core.mcp_server import build_server
from cronometer_core.spec import OPERATIONS


def _spec_names() -> set[str]:
    return {op.name for op in OPERATIONS}


def _cli_names() -> set[str]:
    return set(cli.commands)


def _mcp_names() -> set[str]:
    import asyncio

    server = build_server()

    async def _list():
        async with Client(server) as c:
            return await c.list_tools()

    return {t.name for t in asyncio.run(_list())}


def test_there_are_exactly_8_operations():
    assert len(_spec_names()) == 8


def test_cli_matches_spec():
    assert _cli_names() == _spec_names()


def test_mcp_matches_spec():
    assert _mcp_names() == _spec_names()


def test_cli_mcp_spec_all_identical():
    spec = _spec_names()
    assert _cli_names() == spec == _mcp_names()
