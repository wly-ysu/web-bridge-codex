#!/usr/bin/env sh
set -eu

[ -n "${HOME:-}" ] || { printf '%s\n' "HOME is not set." >&2; exit 1; }
case "$(uname -s)" in
  Darwin) ROOT="$HOME/Library/Application Support/pro_bridge_codex" ;;
  Linux) ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/pro_bridge_codex" ;;
  *) printf '%s\n' "Unsupported operating system." >&2; exit 1 ;;
esac
[ -x "$ROOT/venv/bin/python" ] || { printf '%s\n' "Installation is incomplete. Run install.sh again from a checkout." >&2; exit 1; }
"$ROOT/venv/bin/python" "$ROOT/app/deploy/common/configure_user.py" --codex-config "$HOME/.codex/config.toml" --agents-file "$HOME/.codex/AGENTS.md" --launcher "$ROOT/bin/run-mcp"
printf '%s\n' "UNIX_REPAIR_OK" "Dedicated Chrome profile was preserved. Restart Codex."
