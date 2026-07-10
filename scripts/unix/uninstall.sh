#!/usr/bin/env sh
set -eu

PURGE=false
PURGE_PROFILE=false
for argument in "$@"; do
  case "$argument" in
    --purge) PURGE=true ;;
    --purge-profile) PURGE_PROFILE=true ;;
    *) printf '%s\n' "Unknown option: $argument" >&2; exit 1 ;;
  esac
done
[ -n "${HOME:-}" ] || { printf '%s\n' "HOME is not set." >&2; exit 1; }
case "$(uname -s)" in
  Darwin) ROOT="$HOME/Library/Application Support/pro_bridge_codex" ;;
  Linux) ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/pro_bridge_codex" ;;
  *) printf '%s\n' "Unsupported operating system." >&2; exit 1 ;;
esac
PYTHON="$ROOT/venv/bin/python"
if [ -x "$PYTHON" ] && [ -f "$ROOT/app/deploy/common/configure_user.py" ]; then
  "$PYTHON" "$ROOT/app/deploy/common/configure_user.py" --codex-config "$HOME/.codex/config.toml" --agents-file "$HOME/.codex/AGENTS.md" --remove
fi
rm -rf "$ROOT/app" "$ROOT/venv" "$ROOT/bin"
[ "$PURGE_PROFILE" = true ] && rm -rf "$ROOT/chrome-profile"
[ "$PURGE" = true ] && rm -rf "$ROOT/config" "$ROOT/logs" "$ROOT/backups"
printf '%s\n' "UNIX_UNINSTALL_OK" "Dedicated profile is kept unless --purge-profile was specified. Restart Codex."
