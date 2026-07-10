#!/usr/bin/env sh
set -eu

SOURCE_DIR=${SOURCE_DIR:-"$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"}
SKIP_BROWSER_LAUNCH=${SKIP_BROWSER_LAUNCH:-false}
ACCEPT_AI_PROFILE=${ACCEPT_AI_PROFILE:-false}
NON_INTERACTIVE=${NON_INTERACTIVE:-false}
CHROME_PATH=${CHROME_PATH:-}

for argument in "$@"; do
  case "$argument" in
    --accept-ai-profile) ACCEPT_AI_PROFILE=true ;;
    --non-interactive) NON_INTERACTIVE=true ;;
    --no-open-browser) SKIP_BROWSER_LAUNCH=true ;;
    --chrome-path=*) CHROME_PATH=${argument#--chrome-path=} ;;
    *) printf '%s\n' "Unknown option: $argument" >&2; exit 1 ;;
  esac
done

fail() { printf '%s\n' "Installation failed: $*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"; }

[ "$(id -u)" -ne 0 ] || fail "Run as a normal user, not root."
[ -n "${HOME:-}" ] || fail "HOME is not set."
case "$(uname -s)" in
  Darwin)
    ROOT="$HOME/Library/Application Support/pro_bridge_codex"
    LOG_ROOT="$HOME/Library/Logs/pro_bridge_codex"
    ;;
  Linux)
    ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/pro_bridge_codex"
    LOG_ROOT="${XDG_STATE_HOME:-$HOME/.local/state}/pro_bridge_codex/logs"
    ;;
  *) fail "Only macOS and Linux are supported by this installer." ;;
esac

need python3
PYTHON=$(command -v python3)
"$PYTHON" - <<'PY' || fail "Python 3.11+ is required."
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
"$PYTHON" -m venv --help >/dev/null 2>&1 || fail "Python venv support is required."

find_chrome() {
  if [ -n "$CHROME_PATH" ]; then
    [ -f "$CHROME_PATH" ] && [ -x "$CHROME_PATH" ] || fail "--chrome-path is not an executable file: $CHROME_PATH"
    printf '%s\n' "$CHROME_PATH"
    return
  fi
  if [ "$(uname -s)" = Darwin ]; then
    for path in \
      "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
      "$HOME/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
      "/Applications/Chromium.app/Contents/MacOS/Chromium"; do
      [ -x "$path" ] && { printf '%s\n' "$path"; return; }
    done
  else
    for command in google-chrome google-chrome-stable chromium chromium-browser; do
      command -v "$command" >/dev/null 2>&1 && { command -v "$command"; return; }
    done
  fi
  return 1
}

if ! CHROME=$(find_chrome); then
  if [ "$(uname -s)" = Darwin ]; then
    fail "Google Chrome or Chromium was not found. Install Google Chrome from https://www.google.com/chrome/ , then run this installer again or pass --chrome-path=<path>."
  fi
  fail "Google Chrome or Chromium was not found. Install Google Chrome from https://www.google.com/chrome/ , then run this installer again or pass --chrome-path=<path>."
fi
[ -d "$HOME/.codex" ] || fail "Codex configuration directory ~/.codex was not found. Install and open Codex first."
[ -f "$SOURCE_DIR/server.py" ] || fail "Source directory does not contain server.py: $SOURCE_DIR"

APP="$ROOT/app"
VENV="$ROOT/venv"
CONFIG="$ROOT/config/config.yaml"
PROFILE="$ROOT/chrome-profile"
BIN="$ROOT/bin"
CODEX_CONFIG="$HOME/.codex/config.toml"
AGENTS_FILE="$HOME/.codex/AGENTS.md"
STAGE=$(mktemp -d "${TMPDIR:-/tmp}/pro_bridge_codex.XXXXXX")
cleanup() { rm -rf "$STAGE"; }
trap cleanup EXIT INT TERM

mkdir -p "$ROOT" "$LOG_ROOT" "$ROOT/config" "$BIN"
if [ -e "$PROFILE" ] && [ ! -d "$PROFILE" ]; then
  fail "AI Chrome Profile path exists but is not a directory: $PROFILE"
fi
if [ -d "$PROFILE" ]; then
  PROFILE_ACTION=reuse
else
  PROFILE_ACTION=create
fi
printf '%s\n' "" "Chrome executable: $CHROME" "AI Profile path:   $PROFILE" "Profile action:    $PROFILE_ACTION" "The default Chrome profile will not be copied or modified."
if [ "$NON_INTERACTIVE" = true ]; then
  [ "$ACCEPT_AI_PROFILE" = true ] || fail "Non-interactive installation requires --accept-ai-profile before a dedicated AI Chrome Profile can be created or reused."
elif [ "$ACCEPT_AI_PROFILE" != true ]; then
  [ -r /dev/tty ] && [ -w /dev/tty ] || fail "No interactive terminal is available. Re-run with --non-interactive --accept-ai-profile to explicitly authorize the dedicated AI Profile."
  printf '%s' "Create or reuse this dedicated AI Chrome Profile and open ChatGPT login? [y/N] " > /dev/tty
  IFS= read -r answer < /dev/tty || answer=""
  case "$answer" in
    y|Y|yes|YES|Yes) ;;
    *) fail "AI Chrome Profile creation was cancelled by the user. No browser profile was created or changed." ;;
  esac
fi
if [ "$PROFILE_ACTION" = create ]; then
  mkdir -p "$PROFILE" || fail "Could not create AI Chrome Profile directory: $PROFILE"
fi
mkdir -p "$STAGE/app"
tar -C "$SOURCE_DIR" --exclude=.git --exclude=__pycache__ --exclude=logs --exclude=runtime --exclude=dist --exclude=packaging --exclude=.gptpro-browser --exclude=browser_data --exclude=config.yaml --exclude=bridge_mcp.log --exclude=bridge_launch_matrix.log -cf - . | tar -C "$STAGE/app" -xf -
rm -rf "$APP"
mv "$STAGE/app" "$APP"

if [ ! -f "$CONFIG" ]; then
  "$PYTHON" - "$APP/config.example.yaml" "$CONFIG" "$PROFILE" <<'PY'
from pathlib import Path
import re, sys
source, destination, profile = map(Path, sys.argv[1:])
text = source.read_text(encoding="utf-8")
text = re.sub(r'^  user_data_dir:.*$', f'  user_data_dir: "{profile.as_posix()}"', text, flags=re.M)
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(text, encoding="utf-8")
PY
fi

if [ ! -x "$VENV/bin/python" ]; then
  "$PYTHON" -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install -r "$APP/requirements.txt"

cat > "$BIN/run-mcp" <<EOF
#!/usr/bin/env sh
cd "$APP"
exec "$VENV/bin/python" "$APP/server.py" --config "$CONFIG"
EOF
chmod 700 "$BIN/run-mcp"
cat > "$BIN/launch-web-profile" <<EOF
#!/usr/bin/env sh
exec "$CHROME" --user-data-dir="$PROFILE" --new-window https://chatgpt.com/
EOF
chmod 700 "$BIN/launch-web-profile"

"$VENV/bin/python" "$APP/deploy/common/configure_user.py" --codex-config "$CODEX_CONFIG" --agents-file "$AGENTS_FILE" --launcher "$BIN/run-mcp"
printf '%s\n' "UNIX_INSTALL_OK" "install_root=$ROOT" "chrome_profile=$PROFILE" "chrome=$CHROME"
if [ "$SKIP_BROWSER_LAUNCH" != true ]; then
  "$BIN/launch-web-profile" >/dev/null 2>&1 &
  printf '%s\n' "A dedicated AI browser profile was opened. Sign in to ChatGPT once, then restart Codex."
fi
