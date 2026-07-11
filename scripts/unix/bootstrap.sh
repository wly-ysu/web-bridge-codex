#!/usr/bin/env sh
set -eu

REPOSITORY=${REPOSITORY:-wly-ysu/web-bridge-codex}
REF=${REF:-main}
need() { command -v "$1" >/dev/null 2>&1 || { printf '%s\n' "Missing required command: $1" >&2; exit 1; }; }
need curl
need tar
TEMP=$(mktemp -d "${TMPDIR:-/tmp}/web-bridge-codex.XXXXXX")
trap 'rm -rf "$TEMP"' EXIT INT TERM
curl --fail --location "https://github.com/$REPOSITORY/archive/refs/heads/$REF.tar.gz" -o "$TEMP/source.tar.gz"
tar -xzf "$TEMP/source.tar.gz" -C "$TEMP"
SOURCE=$(find "$TEMP" -mindepth 1 -maxdepth 1 -type d -name 'web-bridge-codex-*' | head -n 1)
[ -n "$SOURCE" ] || { printf '%s\n' "Downloaded archive did not contain the bridge source." >&2; exit 1; }
SOURCE_DIR="$SOURCE" sh "$SOURCE/scripts/unix/install.sh" "$@"

