#!/usr/bin/env python3
"""
Lobster Inbox MCP Server — HTTP Transport

Exposes the existing lobster-inbox MCP server over Streamable HTTP
so remote Claude Code instances can connect to it.

Usage:
    python inbox_server_http.py [--port 8741]
"""

import contextlib
import json
import logging
import os
import subprocess
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

# Import the existing server object with all tools registered
sys.path.insert(0, str(Path(__file__).parent))
from inbox_server import server

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load auth token
AUTH_TOKEN = os.environ.get("MCP_HTTP_TOKEN", "")
if not AUTH_TOKEN:
    auth_file = Path(__file__).parent.parent.parent / "config" / "mcp-http-auth.env"
    if auth_file.exists():
        for line in auth_file.read_text().splitlines():
            if line.strip().startswith("MCP_HTTP_TOKEN="):
                AUTH_TOKEN = line.split("=", 1)[1].strip()
                break

if not AUTH_TOKEN:
    logger.error("No MCP_HTTP_TOKEN configured. Set env var or config/mcp-http-auth.env")
    sys.exit(1)

# Create session manager
session_manager = StreamableHTTPSessionManager(
    app=server,
    stateless=True,
)


@contextlib.asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    async with session_manager.run():
        logger.info("Lobster inbox HTTP MCP server started")
        yield
    logger.info("Lobster inbox HTTP MCP server stopped")


def _check_heartbeat(path, max_stale=600):
    """Check if a heartbeat file is fresh."""
    if not path.exists():
        return {"status": "unknown", "detail": "no heartbeat file"}
    age = time.time() - path.stat().st_mtime
    if age > max_stale:
        return {"status": "down", "detail": f"stale ({int(age)}s)", "age_seconds": int(age)}
    return {"status": "ok", "age_seconds": int(age)}


def _check_process(name):
    """Check if a process is running."""
    try:
        result = subprocess.run(["pgrep", "-f", name], capture_output=True, timeout=5)
        return {"status": "ok"} if result.returncode == 0 else {"status": "down"}
    except Exception:
        return {"status": "unknown"}


async def health_endpoint(scope, receive, send):
    """Return health status of all VPS components."""
    home = Path.home()
    health = {
        "lobster_claude": _check_heartbeat(home / "lobster-workspace" / "logs" / "claude-heartbeat"),
        "amber_claude": _check_heartbeat(home / "amber-workspace" / "logs" / "claude-heartbeat"),
        "lobster_bot": _check_process("lobster_bot.py"),
        "amber_bot": _check_process("amber_bot.py"),
        "http_bridge": {"status": "ok"},
    }
    all_ok = all(c.get("status") == "ok" for c in health.values())
    status_code = 200 if all_ok else 503
    response = JSONResponse({"healthy": all_ok, "components": health}, status_code=status_code)
    await response(scope, receive, send)


async def mcp_endpoint(scope, receive, send):
    """Handle all requests: auth check then delegate to MCP."""
    request = Request(scope, receive)
    path = request.url.path

    # Health endpoint — no auth required
    if path == "/health":
        await health_endpoint(scope, receive, send)
        return

    # Only handle /mcp
    if path != "/mcp":
        response = Response("Not Found", status_code=404)
        await response(scope, receive, send)
        return

    # Auth check
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer ") or auth_header[7:] != AUTH_TOKEN:
        response = Response("Unauthorized", status_code=401)
        await response(scope, receive, send)
        return

    await session_manager.handle_request(scope, receive, send)


# Starlette app with lifespan only (routing handled in mcp_endpoint)
_inner_app = Starlette(lifespan=lifespan)


async def app(scope, receive, send):
    """ASGI entrypoint: lifecycle via Starlette, requests via mcp_endpoint."""
    if scope["type"] == "lifespan":
        await _inner_app(scope, receive, send)
    elif scope["type"] == "http":
        await mcp_endpoint(scope, receive, send)


if __name__ == "__main__":
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8741
    logger.info(f"Starting on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
