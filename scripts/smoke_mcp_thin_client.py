#!/usr/bin/env python3
"""Smoke-test the thin MCP daemon client over stdio."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from fastmcp import Client
from fastmcp.client.transports.stdio import PythonStdioTransport


ROOT = Path(__file__).resolve().parents[1]


def _tool_result_data(result: Any) -> dict[str, Any]:
    for attribute in ("data", "structured_content"):
        value = getattr(result, attribute, None)
        if isinstance(value, dict):
            return value
    content = getattr(result, "content", None)
    if isinstance(content, list) and content:
        text = getattr(content[0], "text", None)
        if isinstance(text, str):
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
    raise RuntimeError(f"tool returned non-object result: {result!r}")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


async def _run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    server_script = Path(args.server_script).resolve()
    _require(server_script.exists(), f"missing thin MCP server script: {server_script}")
    daemon_url = args.daemon_url or os.environ.get("ENGRAM_DAEMON_URL", "").strip()
    server_args = ["--daemon-url", daemon_url] if daemon_url else []
    child_env = os.environ.copy()
    if daemon_url:
        child_env["ENGRAM_DAEMON_URL"] = daemon_url

    transport = PythonStdioTransport(
        server_script,
        args=server_args,
        env=child_env,
        cwd=str(ROOT),
        keep_alive=False,
    )
    async with Client(
        transport,
        timeout=args.timeout,
        init_timeout=args.timeout,
    ) as client:
        tools = await client.list_tools()
        tool_names = {tool.name for tool in tools}
        for required_tool in ("memory_protocol", "daemon_status"):
            _require(required_tool in tool_names, f"thin MCP tool missing: {required_tool}")

        protocol = _tool_result_data(await client.call_tool("memory_protocol", {}))
        daemon_status = _tool_result_data(await client.call_tool("daemon_status", {}))

    health = daemon_status.get("health") if isinstance(daemon_status.get("health"), dict) else {}
    serving = health.get("serving") if isinstance(health.get("serving"), dict) else {}
    _require(
        protocol.get("protocol", {}).get("entrypoint") == "server_daemon_client.py",
        f"unexpected MCP entrypoint: {protocol.get('protocol')}",
    )
    _require(daemon_status.get("reachable") is True, f"daemon not reachable: {daemon_status}")
    _require(health.get("status") == "ok", f"daemon health not ok: {health}")
    _require(
        serving.get("memory_os_retrieval_ready") is True,
        f"Memory OS retrieval not ready through MCP: {serving}",
    )
    return {
        "status": "ok",
        "message": "Thin MCP client reached daemon",
        "tool_count": len(tool_names),
        "protocol_mode": protocol.get("protocol", {}).get("mode"),
        "daemon_url": daemon_status.get("daemon_url"),
        "memory_os_retrieval_status": serving.get("memory_os_retrieval_status"),
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test Engram thin MCP stdio.")
    parser.add_argument(
        "--server-script",
        default=str(ROOT / "server_daemon_client.py"),
        help="Path to server_daemon_client.py.",
    )
    parser.add_argument(
        "--daemon-url",
        default="",
        help="Daemon URL to pass to server_daemon_client.py. Defaults to ENGRAM_DAEMON_URL.",
    )
    parser.add_argument("--timeout", type=float, default=120.0, help="MCP timeout in seconds.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        payload = asyncio.run(_run_smoke(args))
    except Exception as exc:
        print(f"thin MCP smoke failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
