"""Read DataHub through the official MCP Server.

The hackathon's context platform exposes a Model Context Protocol server
(`mcp-server-datahub`) — the same one Claude Desktop and Cursor use. Rather than
only reaching DataHub through the Python SDK, Sentinel can read lineage, schema
and search through that MCP server, so it consumes DataHub the way the ecosystem
intends and inherits new server tools for free.

The server is an stdio process. It is launched once (via `uvx`, isolated from our
pinned venv) and its session is kept open on a background event loop, so the
subprocess and MCP handshake are paid for once per run rather than per call. A
synchronous `call_json` bridges into that loop, because the rest of the agent is
synchronous.

Enabled with SENTINEL_USE_MCP=1; if the server can't start, callers fall back to
the SDK, so this is always additive.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
from typing import Any, Optional


class DataHubMCP:
    """A synchronous handle to the DataHub MCP server over a background loop."""

    def __init__(self, gms_url: Optional[str] = None,
                 token: Optional[str] = None, timeout: float = 60.0) -> None:
        self.gms_url = gms_url or os.getenv("DATAHUB_GMS_URL", "http://localhost:8080")
        self.token = token if token is not None else os.getenv("DATAHUB_GMS_TOKEN", "")
        self.timeout = timeout
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._session = None
        self._stop: Optional[asyncio.Event] = None
        self._ready = threading.Event()
        self._ok = False
        self._start()

    # ------------------------------------------------------------------ #
    def _start(self) -> None:
        threading.Thread(target=self._run_loop, daemon=True).start()
        self._ready.wait(timeout=self.timeout)

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except Exception:
            self._ok = False
            self._ready.set()

    async def _serve(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        env = dict(os.environ)
        env["DATAHUB_GMS_URL"] = self.gms_url
        env["DATAHUB_GMS_TOKEN"] = self.token
        params = StdioServerParameters(
            command="uvx", args=["mcp-server-datahub@latest"], env=env)
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self._session = session
                    self._stop = asyncio.Event()
                    self._ok = True
                    self._ready.set()
                    await self._stop.wait()   # keep the session open until close()
        except Exception:
            self._ok = False
            self._ready.set()

    # ------------------------------------------------------------------ #
    def available(self) -> bool:
        return self._ok and self._session is not None

    def call_json(self, tool: str, args: dict) -> Any:
        """Call an MCP tool and parse its text content as JSON (tools return JSON
        text). Returns {} on failure so a caller can fall back to the SDK."""
        if not self.available():
            return {}
        try:
            fut = asyncio.run_coroutine_threadsafe(
                self._session.call_tool(tool, args), self._loop)
            result = fut.result(timeout=self.timeout)
        except Exception:
            return {}
        text = "".join(getattr(c, "text", "") for c in result.content)
        try:
            return json.loads(text)
        except (ValueError, TypeError):
            return {"_raw": text}

    def close(self) -> None:
        if self._loop and self._stop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._stop.set)


_SINGLETON: Optional[DataHubMCP] = None


def shared_mcp() -> Optional[DataHubMCP]:
    """One MCP server per process, started lazily. Returns None when disabled or
    unavailable, which is the signal to use the SDK instead."""
    global _SINGLETON
    if os.getenv("SENTINEL_USE_MCP", "").lower() not in ("1", "true", "yes"):
        return None
    if _SINGLETON is None:
        client = DataHubMCP()
        if client.available():
            print("  [mcp      ] DataHub MCP Server connected — reading context "
                  "via MCP")
            _SINGLETON = client
        else:
            print("  [mcp      ] DataHub MCP Server unavailable — using the SDK")
            _SINGLETON = None
    return _SINGLETON
