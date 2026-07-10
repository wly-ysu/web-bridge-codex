# Platform support

| Platform | Status | Installation path | Notes |
|---|---|---|---|
| Windows 10/11 x64 | First release target | `%LOCALAPPDATA%\pro_bridge_codex` | User-level PowerShell installer |
| macOS | Initial installer delivered | `~/Library/Application Support/pro_bridge_codex` | Requires Python 3.11+, Chrome/Chromium, and first-run device validation |
| Linux | Initial installer delivered | `~/.local/share/pro_bridge_codex` | Requires Python 3.11+, Chrome/Chromium, and distribution-specific validation |

The Python bridge, YAML configuration, MCP tool contract, and Web-First rule are kept
platform-neutral. Only installation, browser discovery, paths, and process handling are
platform-specific.

macOS and Linux installers are available but remain preview support until each receives a
clean-machine installation and ChatGPT Web end-to-end test.
