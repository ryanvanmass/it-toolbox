#!/usr/bin/env bash
# Headless smoke test of a built IT Toolbox.app (packaging/macos/build.sh's
# output) -- catches a bundle that can't even start (broken interpreter
# relocation, missing Qt cocoa/offscreen plugin, unresolved dylib, bad
# signature) before it ships. Real RDP/SSH/updater behaviour still needs a
# person on a Mac: see docs/macos-status.md.
#
# Usage: smoke_test.sh [path/to/IT Toolbox.app]   (default: build/macos/IT Toolbox.app)
set -euo pipefail
cd "$(dirname "$0")/../.."  # repo root

APP="${1:-build/macos/IT Toolbox.app}"
PY="$APP/Contents/MacOS/python"

codesign --verify --deep --strict "$APP"

# Every module that pulls in a native extension, through the bundle's own
# interpreter symlink (the same path the launcher execs).
"$PY" -c "
import sys
assert sys.prefix.endswith('Contents/Resources/python'), sys.prefix
import it_toolbox.app, PySide6.QtWidgets, cryptography, bcrypt, pyrage, paramiko
from importlib.metadata import version
# build.sh prunes Qt; the .svg app icon still needs the qsvg plugin.
from PySide6.QtGui import QGuiApplication, QImageReader
app = QGuiApplication(['smoke', '-platform', 'offscreen'])
assert b'svg' in [bytes(f) for f in QImageReader.supportedImageFormats()], 'qsvg plugin missing'
print('it-toolbox', version('it-toolbox'), 'on Python', sys.version.split()[0])
"

# Launch the real app through the bundle's launcher and require it to still
# be running after a few seconds -- a crash at startup exits much sooner.
# (macOS has no coreutils `timeout`, hence the manual background/kill.)
LOG=$(mktemp)
QT_QPA_PLATFORM=offscreen "$APP/Contents/MacOS/it-toolbox" >"$LOG" 2>&1 &
PID=$!
sleep 10
if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    wait "$PID" 2>/dev/null || true
    echo "Smoke test passed: app was still running after 10s."
else
    wait "$PID" || STATUS=$?
    echo "App exited early (status ${STATUS:-0}). Output:" >&2
    cat "$LOG" >&2
    exit 1
fi
