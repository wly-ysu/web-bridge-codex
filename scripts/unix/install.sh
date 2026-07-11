#!/usr/bin/env sh
set -eu

SOURCE_DIR=${SOURCE_DIR:-"$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"}
SKIP_BROWSER_LAUNCH=${SKIP_BROWSER_LAUNCH:-false}
ACCEPT_AI_PROFILE=${ACCEPT_AI_PROFILE:-false}
NON_INTERACTIVE=${NON_INTERACTIVE:-false}
CHROME_PATH=${CHROME_PATH:-}
PROFILE_DIR=${PRO_BRIDGE_PROFILE_DIR:-}
CHECK_ONLY=false
DRY_RUN=false
ACCEPT_DEPENDENCY_INSTALL=${ACCEPT_DEPENDENCY_INSTALL:-false}

for argument in "$@"; do
  case "$argument" in
    --accept-ai-profile) ACCEPT_AI_PROFILE=true ;;
    --non-interactive) NON_INTERACTIVE=true ;;
    --no-open-browser) SKIP_BROWSER_LAUNCH=true ;;
    --chrome-path=*) CHROME_PATH=${argument#--chrome-path=} ;;
    --check) CHECK_ONLY=true ;;
    --dry-run) DRY_RUN=true ;;
    --accept-dependency-install) ACCEPT_DEPENDENCY_INSTALL=true ;;
    *) printf '%s\n' "Unknown option: $argument" >&2; exit 1 ;;
  esac
done

fail() { printf '%s\n' "Installation failed: $*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"; }

[ "$(id -u)" -ne 0 ] || fail "Run as a normal user, not root."
[ -n "${HOME:-}" ] || fail "HOME is not set."
case "$(uname -s)" in
  Darwin)
    ROOT="$HOME/Library/Application Support/web-bridge-codex"
    LEGACY_ROOT="$HOME/Library/Application Support/pro_bridge_codex"
    LOG_ROOT="$HOME/Library/Logs/web-bridge-codex"
    ;;
  Linux)
    ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/web-bridge-codex"
    LEGACY_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/pro_bridge_codex"
    LOG_ROOT="${XDG_STATE_HOME:-$HOME/.local/state}/web-bridge-codex/logs"
    ;;
  *) fail "Only macOS and Linux are supported by this installer." ;;
esac

find_python() {
  for command in python3 python; do
    command -v "$command" >/dev/null 2>&1 || continue
    candidate=$(command -v "$command")
    "$candidate" - <<'PY' >/dev/null 2>&1 || continue
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
    "$candidate" -m venv --help >/dev/null 2>&1 || continue
    printf '%s\n' "$candidate"
    return
  done
  return 1
}

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

package_manager() {
  if [ "$(uname -s)" = Darwin ]; then
    command -v brew >/dev/null 2>&1 && { printf '%s\n' brew; return; }
  else
    for command in apt-get dnf yum pacman; do
      command -v "$command" >/dev/null 2>&1 && { printf '%s\n' "$command"; return; }
    done
  fi
  return 1
}

print_dependency_plan() {
  manager=$1
  printf '%s\n' "UNIX_DEPENDENCY_PLAN" "platform=$(uname -s)" "package_manager=${manager:-unavailable}" "python_present=$([ -n "${PYTHON:-}" ] && echo true || echo false)" "browser_present=$([ -n "${CHROME:-}" ] && echo true || echo false)"
  case "$manager" in
    brew)
      [ -n "${PYTHON:-}" ] || printf '%s\n' "install_command=brew install python"
      [ -n "${CHROME:-}" ] || printf '%s\n' "install_command=brew install --cask google-chrome"
      ;;
    apt-get) printf '%s\n' "install_command=sudo apt-get update && sudo apt-get install -y python3 python3-venv chromium" ;;
    dnf|yum) printf '%s\n' "install_command=sudo $manager install -y python3 python3-pip chromium" ;;
    pacman) printf '%s\n' "install_command=sudo pacman -Sy --noconfirm python python-virtualenv chromium" ;;
    *) printf '%s\n' "manual_python=https://www.python.org/downloads/" "manual_browser=https://www.google.com/chrome/" ;;
  esac
}

install_missing_dependencies() {
  manager=$1
  if [ "$manager" != brew ]; then
    command -v sudo >/dev/null 2>&1 || fail "Missing dependencies require administrator approval, but sudo is unavailable. Install Python 3.11+ and Google Chrome/Chromium manually, then re-run this installer."
  fi
  case "$manager" in
    brew)
      [ -n "${PYTHON:-}" ] || brew install python
      [ -n "${CHROME:-}" ] || brew install --cask google-chrome
      ;;
    apt-get) sudo apt-get update && sudo apt-get install -y python3 python3-venv chromium ;;
    dnf) sudo dnf install -y python3 python3-pip chromium ;;
    yum) sudo yum install -y python3 python3-pip chromium ;;
    pacman) sudo pacman -Sy --noconfirm python python-virtualenv chromium ;;
    *) fail "No supported package manager was found. Install Python 3.11+ from https://www.python.org/downloads/ and Chrome from https://www.google.com/chrome/ , then re-run this installer." ;;
  esac
}

PYTHON=$(find_python || true)
CHROME=$(find_chrome || true)
MANAGER=$(package_manager || true)
if [ "$CHECK_ONLY" = true ]; then
  print_dependency_plan "$MANAGER"
  printf '%s\n' "UNIX_DEPENDENCY_CHECK_OK"
  exit 0
fi
if [ -z "$PYTHON" ] || [ -z "$CHROME" ]; then
  print_dependency_plan "$MANAGER"
  if [ "$DRY_RUN" = true ]; then
    printf '%s\n' "UNIX_DRY_RUN_OK"
    exit 0
  fi
  [ -n "$MANAGER" ] || fail "No supported package manager was found. Install Python 3.11+ from https://www.python.org/downloads/ and Chrome from https://www.google.com/chrome/ , then re-run this installer."
  if [ "$NON_INTERACTIVE" = true ]; then
    [ "$ACCEPT_DEPENDENCY_INSTALL" = true ] || fail "Non-interactive installation with missing dependencies requires --accept-dependency-install."
  elif [ "$ACCEPT_DEPENDENCY_INSTALL" != true ]; then
    [ -r /dev/tty ] && [ -w /dev/tty ] || fail "No interactive terminal is available. Re-run with --non-interactive --accept-dependency-install to explicitly authorize dependency installation."
    printf '%s' "Install the missing dependencies using $MANAGER? [y/N] " > /dev/tty
    IFS= read -r answer < /dev/tty || answer=""
    case "$answer" in y|Y|yes|YES|Yes) ;; *) fail "Dependency installation was cancelled by the user." ;; esac
  fi
  install_missing_dependencies "$MANAGER"
  PYTHON=$(find_python || true)
  CHROME=$(find_chrome || true)
fi
[ -n "$PYTHON" ] || fail "Python 3.11+ with venv support is required. Install it from https://www.python.org/downloads/ , then run this installer again."
[ -n "$CHROME" ] || fail "Google Chrome or Chromium was not found. Install Google Chrome from https://www.google.com/chrome/ , then run this installer again or pass --chrome-path=<path>."
[ -d "$HOME/.codex" ] || fail "Codex configuration directory ~/.codex was not found. Install and open Codex first."
[ -f "$SOURCE_DIR/server.py" ] || fail "Source directory does not contain server.py: $SOURCE_DIR"

if [ -e "$LEGACY_ROOT" ]; then
  [ ! -e "$ROOT" ] || fail "Both legacy ($LEGACY_ROOT) and current ($ROOT) bridge directories exist. Installation stopped to avoid data loss; keep the current directory and remove or back up the legacy directory before retrying."
  mv "$LEGACY_ROOT" "$ROOT" || fail "Could not migrate legacy bridge directory. Close the dedicated browser profile and retry."
  if [ -f "$ROOT/config/config.yaml" ]; then
    "$PYTHON" - "$ROOT/config/config.yaml" "$LEGACY_ROOT" "$ROOT" <<'PY'
from pathlib import Path
import sys
path, legacy, current = map(Path, sys.argv[1:])
text = path.read_text(encoding="utf-8")
path.write_text(text.replace(str(legacy), str(current)).replace(legacy.as_posix(), current.as_posix()), encoding="utf-8")
PY
  fi
  printf '%s\n' "legacy_migration=migrated"
fi

APP="$ROOT/app"
VENV="$ROOT/venv"
CONFIG="$ROOT/config/config.yaml"
PROFILE=${PROFILE_DIR:-"$ROOT/chrome-profile"}
BIN="$ROOT/bin"
CODEX_CONFIG="$HOME/.codex/config.toml"
AGENTS_FILE="$HOME/.codex/AGENTS.md"
STAGE=$(mktemp -d "${TMPDIR:-/tmp}/web-bridge-codex.XXXXXX")
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

