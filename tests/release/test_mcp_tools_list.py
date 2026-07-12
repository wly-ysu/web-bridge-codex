#!/usr/bin/env python3
"""Verify a compiled release exposes MCP tools without browser use."""

from __future__ import annotations

import asyncio
import sys
import tomllib
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    executable, config, codex_config = sys.argv[1:4]
    config_text = Path(config).read_text(encoding="utf-8")
    if "capability_order:" not in config_text or "GPT-5.5" in config_text:
        raise SystemExit("Installed bridge config retained legacy fixed model names")
    registration = tomllib.loads(Path(codex_config).read_text(encoding="utf-8"))["mcp_servers"]["web-bridge-codex"]
    registered_args = registration.get("args", [])
    if registered_args != ["--config", Path(config).resolve().as_posix()]:
        raise SystemExit(f"Invalid installed MCP config args: {registered_args!r}")
    if Path(registration["command"]).resolve() != Path(executable).resolve():
        raise SystemExit("Installed MCP command does not point to the compiled executable")
    async with stdio_client(StdioServerParameters(command=registration["command"], args=registered_args)) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            names = {tool.name for tool in (await session.list_tools()).tools}
    missing = {"bridge_health_check", "ask_pro_architect", "route_to_web_lead"} - names
    if missing:
        raise SystemExit(f"Missing compiled MCP tools: {', '.join(sorted(missing))}")
    print("COMPILED_MCP_TOOLS_LIST_OK")


if __name__ == "__main__":
    asyncio.run(main())
