#!/usr/bin/env sh
set -eu

[ -n "${HOME:-}" ] || { printf '%s\n' "HOME is not set." >&2; exit 1; }
case "$(uname -s)" in
  Darwin) ROOT="$HOME/Library/Application Support/web-bridge-codex"; LEGACY_ROOT="$HOME/Library/Application Support/pro_bridge_codex" ;;
  Linux) ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/web-bridge-codex"; LEGACY_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/pro_bridge_codex" ;;
  *) printf '%s\n' "Unsupported operating system." >&2; exit 1 ;;
esac
CONFIG="$ROOT/config/config.yaml"
VENV="$ROOT/venv/bin/python"
MCP_CONFIG="$HOME/.codex/config.toml"
AGENTS="$HOME/.codex/AGENTS.md"
has_mcp=false; [ -f "$MCP_CONFIG" ] && grep -q '^\[mcp_servers\.web-bridge-codex\]' "$MCP_CONFIG" && has_mcp=true
has_rule=false; [ -f "$AGENTS" ] && grep -q 'web-bridge-codex:web-first:start' "$AGENTS" && has_rule=true
printf '%s\n' \
  "UNIX_DOCTOR" \
  "app_present=$([ -d "$ROOT/app" ] && echo true || echo false)" \
  "config_present=$([ -f "$CONFIG" ] && echo true || echo false)" \
  "venv_present=$([ -x "$VENV" ] && echo true || echo false)" \
  "chrome_profile_present=$([ -d "$ROOT/chrome-profile" ] && echo true || echo false)" \
  "codex_mcp_registered=$has_mcp" \
  "web_first_rule_installed=$has_rule" \
  "legacy_install_present=$([ -d "$LEGACY_ROOT" ] && echo true || echo false)"

