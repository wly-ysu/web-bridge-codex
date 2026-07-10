# macOS installation

## Requirements

- macOS with Python 3.11 or newer and `venv` support
- Google Chrome or Chromium already installed
- Codex already opened once, creating `~/.codex`

The installer is user-level only. It does not use `sudo`, Homebrew, or your normal Chrome
profile.

## One command

```sh
curl -fsSL https://raw.githubusercontent.com/wly-ysu/web-bridge-codex/main/scripts/unix/bootstrap.sh | sh
```

It installs to `~/Library/Application Support/pro_bridge_codex`, opens a dedicated Chrome
profile, and registers the local MCP server. Sign in to ChatGPT in that browser and restart
Codex.

Use `sh ~/Library/Application\ Support/pro_bridge_codex/app/scripts/unix/doctor.sh` for a
local health report. Normal uninstall keeps the dedicated profile; add `--purge-profile`
only if you want to remove its login data.
