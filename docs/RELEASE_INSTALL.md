# Native Release Installation

`web-bridge-codex` release packages are source-free one-folder native builds for this project. They contain the MCP executable, bundled Python runtime, and third-party runtime dependencies, but not this project's `server.py`, `adapters/`, `core/`, or `tools/` source directories.

The first run asks permission to create or reuse one dedicated Chrome profile. Sign in to ChatGPT once in that profile, then restart Codex.

## Windows

Before an upgrade or repair, completely exit every Codex window so its active MCP process releases
the installed runtime. Then run in PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force; irm https://raw.githubusercontent.com/wly-ysu/web-bridge-codex/main/scripts/release/bootstrap-windows.ps1 | iex
```

CMD:

```cmd
curl.exe -fsSL -o "%TEMP%\web-bridge-codex_release_bootstrap.cmd" https://raw.githubusercontent.com/wly-ysu/web-bridge-codex/main/scripts/release/bootstrap-windows.cmd && call "%TEMP%\web-bridge-codex_release_bootstrap.cmd"
```

## Windows repair

If an old configuration was corrupted or Codex cannot expose the bridge tools after an
otherwise successful installation, repair the installed configuration without downloading the
native package again:

```powershell
irm https://raw.githubusercontent.com/wly-ysu/web-bridge-codex/main/scripts/release/repair-windows.ps1 | iex
```

This recreates only the bridge configuration and MCP registration. It preserves the dedicated
Chrome Profile. Completely exit Codex after `WINDOWS_BRIDGE_REPAIR_OK`, then reopen it.

## macOS and Linux

```sh
curl -fsSL https://raw.githubusercontent.com/wly-ysu/web-bridge-codex/main/scripts/release/install-unix.sh | sh
```

The installer selects the matching GitHub Release asset: `windows-x64`, `linux-x64`, `macos-x64`, or `macos-arm64`. It requires Codex and Chrome/Chromium. If Chrome is absent, it stops with the official Chrome download URL instead of silently changing the system.

## Verification

After restarting Codex, call `bridge_health_check`. Then call `ask_pro_architect` with:

```text
请只输出 RELEASE_INSTALL_SUCCESS
```

## Contributor Install

The older scripts in `scripts/windows/` and `scripts/unix/` are source-development installers. They are retained for contributors only. End users should use the native release commands above.
