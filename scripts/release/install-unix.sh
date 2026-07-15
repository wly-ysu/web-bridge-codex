#!/usr/bin/env sh
set -eu

REPOSITORY="wly-ysu/web-bridge-codex"; ARTIFACT=""; CHROME_PATH=""; NON_INTERACTIVE=false; ACCEPT_AI_PROFILE=false; SKIP_BROWSER_LAUNCH=false
fail() { printf '%s\n' "ERROR: $*" >&2; exit 1; }
while [ "$#" -gt 0 ]; do
  case "$1" in
    --repository) REPOSITORY=$2; shift 2 ;; --artifact) ARTIFACT=$2; shift 2 ;; --chrome-path) CHROME_PATH=$2; shift 2 ;;
    --non-interactive) NON_INTERACTIVE=true; shift ;; --accept-ai-profile) ACCEPT_AI_PROFILE=true; shift ;; --no-open-browser) SKIP_BROWSER_LAUNCH=true; shift ;;
    *) fail "Unknown option: $1" ;;
  esac
done
case "$(uname -s)" in
  Darwin) PLATFORM=macos; ROOT="${XDG_DATA_HOME:-$HOME/Library/Application Support}/web-bridge-codex" ;;
  Linux) PLATFORM=linux; ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/web-bridge-codex" ;;
  *) fail "Only macOS and Linux are supported." ;;
esac
case "$(uname -m)" in x86_64|amd64) ARCH=x64 ;; arm64|aarch64) ARCH=arm64 ;; *) fail "Unsupported CPU architecture." ;; esac
TARGET="$PLATFORM-$ARCH"; CODEX_HOME=${CODEX_HOME:-$HOME/.codex}
[ -d "$CODEX_HOME" ] || fail "Codex configuration directory is missing: $CODEX_HOME"
command -v unzip >/dev/null 2>&1 || fail "unzip is required."
find_chrome() {
  [ -n "$CHROME_PATH" ] && { [ -x "$CHROME_PATH" ] || fail "Invalid --chrome-path: $CHROME_PATH"; printf '%s\n' "$CHROME_PATH"; return; }
  if [ "$PLATFORM" = macos ]; then for p in "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" "$HOME/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"; do [ -x "$p" ] && { printf '%s\n' "$p"; return; }; done; else for c in google-chrome google-chrome-stable chromium chromium-browser; do command -v "$c" >/dev/null 2>&1 && { command -v "$c"; return; }; done; fi
  fail "Chrome or Chromium is required. Install it from https://www.google.com/chrome/ and rerun this installer."
}
CHROME=$(find_chrome); PROFILE="$ROOT/chrome-profile"
if [ "$NON_INTERACTIVE" = true ] && [ "$ACCEPT_AI_PROFILE" != true ]; then fail "Non-interactive installation requires --accept-ai-profile."; fi
if [ "$NON_INTERACTIVE" != true ] && [ "$ACCEPT_AI_PROFILE" != true ]; then printf 'Create or reuse dedicated AI Chrome Profile at %s? [y/N] ' "$PROFILE"; read -r answer || answer=""; case "$answer" in y|Y|yes|YES|Yes) ;; *) fail "AI Chrome Profile creation was cancelled." ;; esac; fi
STAGE=$(mktemp -d "${TMPDIR:-/tmp}/web-bridge-codex.XXXXXX"); trap 'rm -rf "$STAGE"' EXIT INT TERM
ARCHIVE=${ARTIFACT:-"$STAGE/web-bridge-codex-$TARGET.zip"}
if [ -z "$ARTIFACT" ]; then command -v curl >/dev/null 2>&1 || fail "curl is required."; curl -fsSL "https://github.com/$REPOSITORY/releases/latest/download/web-bridge-codex-$TARGET.zip" -o "$ARCHIVE"; fi
unzip -q "$ARCHIVE" -d "$STAGE/unpack"; PACKAGE="$STAGE/unpack/web-bridge-codex-$TARGET"; EXE="$PACKAGE/web-bridge-codex"
[ -x "$EXE" ] && [ -f "$PACKAGE/config.example.yaml" ] || fail "Invalid release archive for $TARGET."
if [ -x "$ROOT/app/web-bridge-codex" ] && [ -f "$ROOT/config/config.yaml" ]; then
  "$ROOT/app/web-bridge-codex" --shutdown-broker --config "$ROOT/config/config.yaml" >/dev/null 2>&1 || true
  broker_wait=0
  while command -v pgrep >/dev/null 2>&1 && pgrep -f "$ROOT/app.*--browser-broker" >/dev/null 2>&1 && [ "$broker_wait" -lt 50 ]; do sleep 0.2; broker_wait=$((broker_wait + 1)); done
fi
if command -v pgrep >/dev/null 2>&1 && pgrep -f "$ROOT/app" >/dev/null 2>&1; then fail "Close Codex before upgrading web-bridge-codex."; fi
mkdir -p "$ROOT/config" "$ROOT/logs" "$PROFILE"; rm -rf "$ROOT/app"; mv "$PACKAGE" "$ROOT/app"; CONFIG="$ROOT/config/config.yaml"
if [ -f "$CONFIG" ] && { ! grep -Eq '^  local_execution_prefix:[[:space:]]*"[^"]*"[[:space:]]*$' "$CONFIG" || grep -Eq '^[[:space:]]+preferred_models:[[:space:]]*$' "$CONFIG"; }; then cp "$CONFIG" "$CONFIG.bridge-backup-$(date +%Y%m%d-%H%M%S)"; rm -f "$CONFIG"; printf '%s\n' "Migrated invalid or legacy bridge configuration to the current capability-based model policy."; fi
if [ ! -f "$CONFIG" ]; then awk -v profile="$PROFILE" -v chrome="$CHROME" '/^  user_data_dir:/ { print "  user_data_dir: \"" profile "\""; next } /^  executable_path:/ { print "  executable_path: \"" chrome "\""; next } { print }' "$ROOT/app/config.example.yaml" > "$CONFIG"; fi
"$ROOT/app/web-bridge-codex" --configure-user --config "$CONFIG" --codex-config "$CODEX_HOME/config.toml" --agents-file "$CODEX_HOME/AGENTS.md" --launcher "$ROOT/app/web-bridge-codex" --log-path "$ROOT/logs/bridge_mcp.log"
if [ -f "$ROOT/app/server.py" ] || [ -d "$ROOT/app/adapters" ] || [ -d "$ROOT/app/core" ] || [ -d "$ROOT/app/tools" ] || [ -d "$ROOT/app/deploy" ]; then fail "Release installation contains project source files and was rejected."; fi
if [ "$SKIP_BROWSER_LAUNCH" != true ]; then "$CHROME" --user-data-dir="$PROFILE" --new-window https://chatgpt.com/ >/dev/null 2>&1 & fi
printf '%s\n' "UNIX_RELEASE_INSTALL_OK" "install_root=$ROOT" "launcher=$ROOT/app/web-bridge-codex" "next_action=Sign in to ChatGPT once in the dedicated profile, then restart Codex."
