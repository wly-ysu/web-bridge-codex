# Windows one-click installation

## What the installer does

The Windows installer creates a user-only installation under:

```text
%LOCALAPPDATA%\pro_bridge_codex
```

It creates an isolated Python runtime, installs the bridge dependencies, creates a
dedicated Chrome profile, registers the `pro_bridge_codex` MCP server, and installs a
managed Web-First rule in `%USERPROFILE%\.codex\AGENTS.md`.

The managed rule makes Web Lead the default for every natural-language Codex request.
Explicit deterministic local work (for example a specified Git command, file read, build,
or test) stays local, and Web failures cannot cause an infinite route loop.

It never copies the default Chrome profile, passwords, cookies, or ChatGPT login data.
You sign in manually in the dedicated browser window.

## Install from a local checkout

Open PowerShell in the repository and run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\windows\install.ps1
```

## Install from GitHub

For the current public `main` branch:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
irm https://raw.githubusercontent.com/wly-ysu/web-bridge-codex/main/scripts/windows/bootstrap.ps1 | iex
```

The first launch opens a dedicated Chrome profile. Sign in to ChatGPT in that window,
then restart Codex.

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
