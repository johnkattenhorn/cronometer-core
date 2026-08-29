"""Tests for the FastMCP server (cronometer_core.mcp_server).

Uses FastMCP's in-memory Client. Async calls are driven with ``asyncio.run``
via a small helper so no pytest-asyncio plugin is required.
"""
from __future__ import annotations

import asyncio
import json
import time

import responses
from fastmcp import Client

from cronometer_core.auth import PasswordSessionAuth
from cronometer_core.client import CronometerClient
from cronometer_core.config import Config
from cronometer_core.mcp_server import build_server
from cronometer_core.spec import OPERATIONS

BASE = "https://cronometer.com"
EXPORT = f"{BASE}/export"
TARGETS = f"{BASE}/api/v3/user/12345/targets"

DAILY_CSV = (
    "Date,Energy (kcal),Protein (g),Carbs (g),Fat (g),Fiber (g)\n"
    "2026-07-20,2000,150,180,70,30\n"
)


def make_client() -> CronometerClient:
    auth = PasswordSessionAuth("u@example.com", "pw")
    auth._state = {
        "nonce": "n",
        "userId": "12345",
        "authToken": "tok-abc",
        "tokenExpiry": (time.time() + 3600) * 1000.0,
    }
    return CronometerClient(
        Config(username="u@example.com", password="pw", base_url=BASE),
        auth=auth,
        session=auth.session,
        max_retries=0,
        backoff=0.0,
        sleep=lambda _: None,
    )


def run_async(coro):
    return asyncio.run(coro)


def test_exactly_8_tools_match_spec_names():
    server = build_server(client=make_client())

    async def _list():
        async with Client(server) as c:
            return await c.list_tools()

    tools = run_async(_list())
    names = {t.name for t in tools}
    expected = {op.name for op in OPERATIONS}
    assert names == expected
    assert len(names) == 8


@responses.activate
def test_get_daily_nutrition_returns_mocked_data():
    responses.add(responses.GET, EXPORT, body=DAILY_CSV, status=200)
    server = build_server(client=make_client())

    async def _call():
        async with Client(server) as c:
            return await c.call_tool("get-daily-nutrition", {"date": "2026-07-20"})

    res = run_async(_call())
    # A top-level list is returned as text content (MCP structured data must be
    # an object), so parse the JSON payload back out.
    payload = json.loads(res.content[0].text)
    assert payload[0]["energy_kcal"] == 2000
    assert payload[0]["date"] == "2026-07-20"


@responses.activate
def test_read_tool_text_returns_formatted_text():
    responses.add(responses.GET, EXPORT, body=DAILY_CSV, status=200)
    server = build_server(client=make_client())

    async def _call():
        async with Client(server) as c:
            return await c.call_tool(
                "get-daily-nutrition", {"date": "2026-07-20", "text": True}
            )

    res = run_async(_call())
    text = res.content[0].text
    assert "Daily nutrition" in text
    assert "2000 kcal" in text


@responses.activate
def test_get_targets_tool():
    data = [{"id": 203, "min": 150, "max": 150, "custom": False}]
    responses.add(responses.GET, TARGETS, json=data, status=200)
    server = build_server(client=make_client())

    async def _call():
        async with Client(server) as c:
            return await c.call_tool("get-targets", {})

    res = run_async(_call())
    assert res.data["protein"]["min"] == 150


def test_health_custom_route():
    from starlette.testclient import TestClient

    server = build_server(client=make_client())
    app = server.http_app()
    with TestClient(app) as tc:
        resp = tc.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "cronometer-mcp"}
