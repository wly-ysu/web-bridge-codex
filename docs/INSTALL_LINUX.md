# Linux installation

## Requirements

- Linux with Python 3.11 or newer and `venv` support
- Google Chrome or Chromium already installed and available on `PATH`
- Codex already opened once, creating `~/.codex`

The installer is user-level only. It does not use `sudo` or install system packages.

## One command

```sh
curl -fsSL https://raw.githubusercontent.com/wly-ysu/web-bridge-codex/main/scripts/unix/bootstrap.sh | sh
```

It installs to `${XDG_DATA_HOME:-$HOME/.local/share}/pro_bridge_codex`, opens a dedicated
Chrome profile, and registers the local MCP server. Sign in to ChatGPT in that browser and
restart Codex.

Use `sh ~/.local/share/pro_bridge_codex/app/scripts/unix/doctor.sh` for a local health
report when the default XDG data path is used. Normal uninstall preserves the dedicated
profile; add `--purge-profile` only if you want to remove its login data.
