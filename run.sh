#!/usr/bin/env bash
# Start claudeyes. Keep this in a terminal tab, or wrap it in a launchd plist.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export CLAUDEYES_HOME="${CLAUDEYES_HOME:-$HOME/.claudeyes}"
export CLAUDEYES_SOCK="$CLAUDEYES_HOME/actions.sock"
mkdir -p "$CLAUDEYES_HOME"
BIN="$ROOT/capture/.build/release/claudeyes-capture"
[ -x "$BIN" ] || { echo "not built: cd $ROOT/capture && swift build -c release" >&2; exit 1; }
export CLAUDEYES_FPS="${CLAUDEYES_FPS:-4}"
echo "claudeyes: ${CLAUDEYES_FPS}fps -> $CLAUDEYES_HOME/events.db" >&2
exec "$BIN" | exec python3 -m claudeyes.daemon --db "$CLAUDEYES_HOME/events.db"
