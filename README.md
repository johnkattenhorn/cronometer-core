# cronometer-core

Shared Python core for a **Cronometer CLI** and a **Cronometer MCP server**,
so an assistant (Claude, or any MCP client) can read your own Cronometer
nutrition and biometric data.

All API-client, auth, model, and business logic lives in `src/cronometer_core/`
**once**. `spec.py` declares every operation, and both adapters are generated
from it, so the CLI and MCP surfaces can never drift:

- `cronometer_core.cli:cli` — a `click` CLI (`cronometer <command> [switches]`).
- `cronometer_core.mcp_server:main` — a FastMCP server (Streamable HTTP) whose
  tools are a 1:1 wrapper of the CLI switches.

Output is normalised JSON by default; `--text` (CLI) / `text=true` (MCP read
tools) renders a human-readable view. Cronometer has no public API key — auth is
a session + GWT-RPC login handshake using your ordinary cronometer.com
username/password. Everything is **read-only**.

## Layout

| Module | Role |
|---|---|
| `config.py` | Resolve `CRONOMETER_USERNAME` / `CRONOMETER_PASSWORD` / base URL. |
| `errors.py` | Typed `CronometerError` taxonomy. |
| `auth.py` | `PasswordSessionAuth` — the GWT-RPC login handshake + session. |
| `client.py` | `CronometerClient` — HTTP + retry/backoff + rate-limit handling. |
| `models.py` | CSV parsers + number-normalisation + nutrient IDs. |
| `operations.py` | **Single source of truth** — one pure function per op. |
| `spec.py` | Declarative op registry that drives both adapters. |
| `format.py` | Human-readable rendering (`--text`). |
| `cli.py` / `mcp_server.py` | Thin adapters generated from `spec.py`. |

## Develop

```bash
pip install -e '.[dev]'
ruff check . && mypy && pytest --cov
```

Requires Python 3.10+ (FastMCP). The bundled `python:3.12-slim` Dockerfile
matches the version CI builds against.

## Configuration

| Env var | Required | Default |
|---|---|---|
| `CRONOMETER_USERNAME` | yes | — |
| `CRONOMETER_PASSWORD` | yes | — |
| `CRONOMETER_BASE_URL` | no | `https://cronometer.com` |
| `MCP_TRANSPORT` | no | `http` |
| `PORT` | no | `3000` |

## Attribution

Licensed MIT — see `LICENSE`. Cronometer has no public API; this uses the same
session/GWT-RPC path the website does, with **your own** account credentials,
and is **read-only**. It is unofficial and not affiliated with Cronometer.
