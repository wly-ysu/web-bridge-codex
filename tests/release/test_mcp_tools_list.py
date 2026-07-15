#!/usr/bin/env python3
"""Verify a compiled release exposes MCP tools without browser use."""

from __future__ import annotations

import asyncio
import sys
import tempfile
import tomllib
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    executable, config, codex_config = sys.argv[1:4]
    config_text = Path(config).read_text(encoding="utf-8")
    legacy_config_tokens = (
        "GPT-5.5",
        "ask_pro_architect",
        "review_pro_code",
        "debug_pro_error",
        "pro_deep",
        "pro_review",
        "pro_debug",
        "pro_profile",
        "pro_budget_policy",
        "prefer_gpt55",
        "gptpro",
    )
    if (
        "schema_version: 2" not in config_text
        or "capability_order:" not in config_text
        or any(token in config_text for token in legacy_config_tokens)
    ):
        raise SystemExit("Installed bridge config retained legacy fixed model names")
    registration = tomllib.loads(Path(codex_config).read_text(encoding="utf-8"))["mcp_servers"]["web-bridge-codex"]
    registered_args = registration.get("args", [])
    if registered_args != ["--config", Path(config).resolve().as_posix()]:
        raise SystemExit(f"Invalid installed MCP config args: {registered_args!r}")
    if Path(registration["command"]).resolve() != Path(executable).resolve():
        raise SystemExit("Installed MCP command does not point to the compiled executable")
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as server_stderr:
        async with stdio_client(
            StdioServerParameters(command=registration["command"], args=registered_args),
            errlog=server_stderr,
        ) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
                names = {tool.name for tool in tools}
        server_stderr.seek(0)
        stderr_text = server_stderr.read()
    if "Traceback" in stderr_text or "ValueError: I/O operation on closed file" in stderr_text:
        raise SystemExit(f"Compiled MCP server emitted a shutdown error:\n{stderr_text}")
    missing = {
        "bridge_health_check",
        "bridge_browser_status",
        "bridge_browser_shutdown",
        "ask_web_architect",
        "route_to_web_lead",
    } - names
    if missing:
        raise SystemExit(f"Missing compiled MCP tools: {', '.join(sorted(missing))}")
    by_name = {tool.name: tool for tool in tools}
    ask_schema = by_name["ask_web_architect"].inputSchema
    ask_props = ask_schema.get("properties", {}) if isinstance(ask_schema, dict) else {}
    if "profile" not in ask_props:
        raise SystemExit("ask_web_architect schema is missing profile")
    if "conversation_mode" not in ask_props:
        raise SystemExit("ask_web_architect schema is missing conversation_mode")
    print("COMPILED_MCP_TOOLS_LIST_OK")


if __name__ == "__main__":
    asyncio.run(main())
