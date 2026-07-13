# Global Web-First routing

`web-bridge-codex` is delivered as two cooperating Codex integrations. Installing only the MCP
server is not enough to make Codex route normal project conversations to ChatGPT Web.

## Required target paths

Unless `CODEX_HOME` is configured, Codex uses these Windows user-level paths:

```text
%USERPROFILE%\.codex\config.toml
%USERPROFILE%\.codex\AGENTS.md
```

If `CODEX_HOME` is set, replace `%USERPROFILE%\.codex` with that directory. Run the installer
using the same Windows user that starts Codex. Do not install as a different administrator and
then run Codex as a standard user.

## Layer 1: MCP registration

The canonical server entry is `web-bridge-codex`. Its public, redacted shape is:

```toml
[mcp_servers.web-bridge-codex]
command = "<INSTALL_ROOT>/runtime/Scripts/python.exe"
args = [
  "<INSTALL_ROOT>/app/server.py",
  "--config",
  "<INSTALL_ROOT>/config/config.yaml",
]
enabled = true
```

`<INSTALL_ROOT>` is `%LOCALAPPDATA%\web-bridge-codex` on Windows. The installer preserves
unrelated MCP entries and migrates the historical `pro_bridge_codex` registration to the
canonical name on upgrade.

This layer provides the tools, including `route_to_web_lead`, `ask_web_architect`, and health
checks. A server shown as enabled in the Codex UI proves only that this registration exists.

## Layer 2: global Web-First instruction

The installer adds a clearly marked, managed block to `%USERPROFILE%\.codex\AGENTS.md`. Its
meaning is:

```text
For natural-language project requests, call route_to_web_lead first.
If it is unavailable, call ask_web_architect.
Use the returned Web plan before implementing, reviewing, debugging, or deciding.
Only an explicit "本地执行：" deterministic local request bypasses Web Lead.
```

This is the layer that makes normal project conversations use ChatGPT Web as the planner and
Codex as the local executor. The installer must append only its marked block, never replace a
user's unrelated instructions. It must also remove only that block on uninstall.

`AGENTS.override.md` in the same directory overrides `AGENTS.md`. If it exists, it must retain
the same Web-First policy or automatic routing can be suppressed.

## Post-install verification

Fully quit Codex and open a new task after installation. Existing tasks do not reliably reload
new MCP registrations or global instructions.

Run this in PowerShell under the same Windows user as Codex:

```powershell
$codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
$installRoot = Join-Path $env:LOCALAPPDATA 'web-bridge-codex'

& "$installRoot\app\scripts\windows\verify-install.ps1"
Test-Path "$codexHome\config.toml"
Test-Path "$codexHome\AGENTS.md"
Test-Path "$codexHome\AGENTS.override.md"
```

Expected installer verification fields include:

```text
codex_mcp_registered=True
web_first_rule_installed=True
```

Then, in Codex:

```text
bridge_health_check
```

and:

```text
ask_web_architect

question: 请只输出 WEB_FIRST_RUNTIME_SUCCESS
```

Finally, use a normal project request without naming a tool. Codex should call Web Lead before
responding or implementing.

## Enabled but not automatically invoked

Compare the failing device with the working device in this order:

1. Confirm `bridge_health_check` is visible. If not, the MCP registration is not loaded.
2. Run `verify-install.ps1`. If it fails, retain its output and repair the local install.
3. Check both `AGENTS.md` and `AGENTS.override.md`. A visible MCP server without the Web-First
   rule can be called manually but is not required to be selected automatically.
4. Ensure installer PowerShell and Codex use the same `%USERPROFILE%` and `CODEX_HOME`.
5. Fully exit Codex, reopen it, and retry with a public marker request before investigating
   ChatGPT login or browser automation.

Never submit a complete `config.toml`, browser profile, cookies, tokens, API keys, private keys,
or internal paths for troubleshooting. Share only the relevant server header, field names,
redacted paths, and `verify-install.ps1` result.
