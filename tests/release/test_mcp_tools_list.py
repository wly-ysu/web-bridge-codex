#!/usr/bin/env python3
"""Verify a compiled release exposes MCP tools without browser use."""

from __future__ import annotations

import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    executable, config = sys.argv[1:3]
    async with stdio_client(StdioServerParameters(command=executable, args=["--config", config])) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            names = {tool.name for tool in (await session.list_tools()).tools}
    missing = {"bridge_health_check", "ask_pro_architect", "route_to_web_lead"} - names
    if missing:
        raise SystemExit(f"Missing compiled MCP tools: {', '.join(sorted(missing))}")
    print("COMPILED_MCP_TOOLS_LIST_OK")


if __name__ == "__main__":
    asyncio.run(main())
