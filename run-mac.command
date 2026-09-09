#!/bin/zsh
set -e

ROOT="$(cd -- "$(dirname -- "$0")" && pwd)"
export QT_PLUGIN_PATH="$ROOT/qt-plugins"
export QT_QPA_PLATFORM=cocoa

cd "$ROOT"
exec "$ROOT/.venv/bin/python" -m pet "$@"
