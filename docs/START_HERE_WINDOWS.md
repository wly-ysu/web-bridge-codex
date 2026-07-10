# Windows: one-click deployment

This is the only deployment command needed on a new Windows 10/11 machine that already
has Codex installed:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force; irm https://raw.githubusercontent.com/wly-ysu/web-bridge-codex/main/scripts/windows/bootstrap.ps1 | iex
```

The installer automatically creates a local, isolated deployment at:

```text
%LOCALAPPDATA%\pro_bridge_codex
```

It automatically:

- installs Python with `winget` when missing;
- installs Google Chrome with `winget` when missing;
- installs bridge dependencies into an isolated virtual environment;
- creates an isolated AI Chrome profile, never touching the normal Chrome profile;
- registers the `pro_bridge_codex` MCP server in Codex;
- installs the managed Web-First rule so natural-language requests use ChatGPT Web as the
  planner and Codex as the local executor.

At the end of installation, a dedicated AI Chrome window always opens automatically. The
only manual action is logging into ChatGPT once in that popup window. Then restart Codex
and call `ask_pro_architect` once.

If `winget` is unavailable, the installer stops safely and prints the official Python or
Chrome download link. Install the missing program and run the exact same one-line command
again; installation is idempotent and does not duplicate MCP entries or browser profiles.
