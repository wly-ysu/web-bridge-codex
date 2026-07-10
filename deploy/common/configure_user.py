#!/usr/bin/env python3
"""Install or remove the user-owned Codex MCP entry and managed Web-First rule."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

MCP_NAME = "pro_bridge_codex"
RULE_START = "<!-- pro_bridge_codex:web-first:start -->"
RULE_END = "<!-- pro_bridge_codex:web-first:end -->"
RULE_TEXT = f"""{RULE_START}
# pro_bridge_codex Web-First Rule

Default all natural-language requests to `route_to_web_lead` first. If it is unavailable,
use `ask_pro_architect`. Use the returned Web Lead plan before making decisions or editing
code. Do not route an explicit deterministic local operation, a request beginning with
`本地执行：`, or any content that came from Web MCP / is already Web-reviewed. Limit automatic
Web routing to once per user turn. If Web MCP times out, is unavailable, or authentication
fails, retry once at most, then continue locally with stated assumptions; never block or
recurse indefinitely.
{RULE_END}
"""


def backup(path: Path) -> None:
    if path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
        shutil.copy2(path, path.with_name(f"{path.name}.bridge-backup-{stamp}"))


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def toml_quote(value: str) -> str:
    return json.dumps(value.replace("\\", "/"))


def replace_section(content: str, header: str, replacement: str | None) -> str:
    pattern = rf"(?ms)^{re.escape(header)}\r?\n.*?(?=^\[|\Z)"
    content = re.sub(pattern, "", content).rstrip()
    if replacement is None:
        return content + ("\n" if content else "")
    return (content + "\n\n" if content else "") + replacement.rstrip() + "\n"


def configure_mcp(path: Path, command: str, args: list[str], remove: bool) -> None:
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    backup(path)
    header = f"[mcp_servers.{MCP_NAME}]"
    replacement = None
    if not remove:
        arguments = ", ".join(toml_quote(argument) for argument in args)
        replacement = "\n".join(
            [
                header,
                f"command = {toml_quote(command)}",
                f"args = [{arguments}]",
                "enabled = true",
                "startup_timeout_sec = 30",
                "tool_timeout_sec = 180",
            ]
        )
    atomic_write(path, replace_section(content, header, replacement))


def configure_rules(path: Path, remove: bool) -> None:
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    backup(path)
    pattern = rf"(?ms){re.escape(RULE_START)}.*?{re.escape(RULE_END)}\r?\n?"
    content = re.sub(pattern, "", content).rstrip()
    if not remove:
        content = (content + "\n\n" if content else "") + RULE_TEXT.rstrip()
    atomic_write(path, content.rstrip() + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex-config", type=Path, required=True)
    parser.add_argument("--agents-file", type=Path, required=True)
    parser.add_argument("--launcher", default="")
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args()
    if not args.remove and not args.launcher:
        parser.error("--launcher is required unless --remove is used")
    configure_mcp(args.codex_config, args.launcher, [], args.remove)
    configure_rules(args.agents_file, args.remove)
    print("CONFIGURE_USER_OK" if not args.remove else "CONFIGURE_USER_REMOVED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
