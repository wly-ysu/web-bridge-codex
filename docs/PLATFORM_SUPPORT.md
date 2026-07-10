# Platform support

| Platform | Status | Installation path | Notes |
|---|---|---|---|
| Windows 10/11 x64 | First release target | `%LOCALAPPDATA%\pro_bridge_codex` | User-level PowerShell installer |
| macOS | Planned | `~/Library/Application Support/pro_bridge_codex` | Needs shell installer, Chrome path discovery, and Codex config verification |
| Linux | Planned | `~/.local/share/pro_bridge_codex` | Needs shell installer, package-manager guidance, and Chrome/Chromium discovery |

The Python bridge, YAML configuration, MCP tool contract, and Web-First rule are kept
platform-neutral. Only installation, browser discovery, paths, and process handling are
platform-specific.

macOS and Linux are not yet declared supported because they have not received a clean
machine installation test.
