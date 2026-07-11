# Windows one-click installation

## What the installer does

The Windows installer creates a user-only installation under:

```text
%LOCALAPPDATA%\web-bridge-codex
```

It creates an isolated Python runtime, installs the bridge dependencies, creates a
dedicated Chrome profile, registers the `web-bridge-codex` MCP server, and installs a
managed Web-First rule in `%USERPROFILE%\.codex\AGENTS.md`.

The managed rule makes Web Lead the default for every natural-language Codex request.
Explicit deterministic local work (for example a specified Git command, file read, build,
or test) stays local, and Web failures cannot cause an infinite route loop.

It never copies the default Chrome profile, passwords, cookies, or ChatGPT login data.
You sign in manually in the dedicated browser window.

## Codex target paths and routing contract

The installation is intentionally split into two user-level Codex files:

```text
%USERPROFILE%\.codex\config.toml  -> MCP process registration
%USERPROFILE%\.codex\AGENTS.md    -> Global Web-First routing instruction
```

The MCP registration makes the tools available. The managed `AGENTS.md` block makes normal
natural-language project requests use `route_to_web_lead`, with `ask_pro_architect` as the
compatibility fallback. Both files must be associated with the same Windows user that runs Codex.

The canonical MCP server name is `web-bridge-codex`. An earlier installation may contain the
legacy `pro_bridge_codex` server name; the current installer migrates the legacy entry during an
upgrade so only the canonical entry remains. Do not copy a full `config.toml` from another
device: it can contain unrelated MCP registrations or personal settings.

`%USERPROFILE%\.codex\AGENTS.override.md` takes precedence when it exists. If automatic routing
does not occur, inspect that override before changing the managed rule.

## Install from a local checkout

On a device that already has Codex, the shortest installation is one command:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force; irm https://raw.githubusercontent.com/wly-ysu/web-bridge-codex/main/scripts/windows/bootstrap.ps1 | iex
```

The installer uses `winget` to install Python and Google Chrome if missing. If `winget`
is unavailable, it stops before registering MCP and displays the official download link;
install the missing program and run the same command again.

From `cmd.exe`, use the native CMD entrypoint:

```cmd
curl.exe -fsSL -o "%TEMP%\web-bridge-codex_bootstrap.cmd" https://raw.githubusercontent.com/wly-ysu/web-bridge-codex/main/scripts/windows/bootstrap.cmd && call "%TEMP%\web-bridge-codex_bootstrap.cmd"
```

To install from a local checkout instead, open PowerShell in the repository and run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\windows\install.ps1
```

Before creating browser data, the installer displays the detected Chrome path and AI
Profile path. Enter `y` when it asks for approval to create or reuse that dedicated,
isolated Profile. It then opens the dedicated Chrome login window. Sign in to ChatGPT once
in that window, then restart Codex.

## Verify

Run:

```powershell
.\scripts\windows\doctor.ps1
.\scripts\windows\verify-install.ps1
```

Expected fields include `codex_mcp_registered=True` and
`web_first_rule_installed=True`. `verify-install.ps1` also imports the installed MCP
server with the generated local configuration. In Codex, call `bridge_health_check`,
then use:

```text
ask_pro_architect
profile: fast
include_workspace_context: false
question: 请只输出 WINDOWS_INSTALL_SUCCESS
```

For a detailed redacted configuration shape and the difference between a registered MCP and an
automatically routed request, see [CODEX_GLOBAL_ROUTING.md](CODEX_GLOBAL_ROUTING.md).

## Repair, upgrade, uninstall

Run these from the installed source checkout or from a new checkout:

```powershell
.\scripts\windows\repair.ps1
.\scripts\windows\repair.ps1 -ReinstallDependencies
.\scripts\windows\uninstall.ps1
.\scripts\windows\uninstall.ps1 -PurgeUserData
```

The standard uninstall keeps the dedicated browser profile and local configuration.
`-PurgeUserData` removes them after unregistering the MCP server.

## Requirements and limits

- Windows 10/11 x64
- Internet access for Python packages
- Google Chrome for ChatGPT Web automation
- Codex desktop installed for MCP registration
- User-managed ChatGPT login; the installer does not automate authentication

If Python is absent, the installer attempts a user-scoped `winget` installation. If
`winget` is unavailable, it explains the next manual action without changing system
security policy.


