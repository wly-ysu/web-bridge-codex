# Security and privacy

- The bridge uses a dedicated local Chrome profile rather than the user's default profile.
- ChatGPT authentication is completed manually by the user in that dedicated browser.
- Browser profiles, logs, local configuration, cookies, and runtime data are excluded from Git.
- The Windows installer backs up Codex configuration before changing the bridge MCP entry.
- MCP registration updates only `[mcp_servers.web-bridge-codex]` and preserves other servers.
- The managed Web-First rule is marked so uninstall can remove only its own block.
- No remote debugging port is exposed by the installer.
- Do not publish `%LOCALAPPDATA%\web-bridge-codex`, `.codex` backups, or ChatGPT profile data.


