#!/bin/bash
set -euo pipefail

# Run from the project directory so relative paths are stable.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "[0/4] Preparing macOS permissions..."
chmod +x "$SCRIPT_DIR"/*.command 2>/dev/null || true
if command -v xattr >/dev/null 2>&1; then
    xattr -dr com.apple.quarantine "$SCRIPT_DIR" 2>/dev/null || true
fi

echo "[1/4] Locating Python 3..."
PY_CMD=""
if command -v python3 >/dev/null 2>&1; then
    PY_CMD="python3"
elif command -v python >/dev/null 2>&1; then
    PY_CMD="python"
fi

if [[ -z "$PY_CMD" ]]; then
    echo
    echo "Python 3 was not found on this Mac."
    echo "Install Python 3 and run this installer again."
    read -r -p "Press Enter to close..."
    exit 1
fi

if ! "$PY_CMD" -c 'import sys; raise SystemExit(0 if sys.version_info.major == 3 else 1)'; then
    echo
    echo "A Python interpreter was found, but it is not Python 3."
    echo "Install Python 3 and run this installer again."
    read -r -p "Press Enter to close..."
    exit 1
fi

echo "[2/4] Creating virtual environment..."
if [[ ! -x ".venv/bin/python3" && ! -x ".venv/bin/python" ]]; then
    "$PY_CMD" -m venv ".venv"
fi

VENV_PY=".venv/bin/python3"
if [[ ! -x "$VENV_PY" ]]; then
    VENV_PY=".venv/bin/python"
fi
if [[ ! -x "$VENV_PY" ]]; then
    echo "Failed to create virtual environment."
    read -r -p "Press Enter to close..."
    exit 1
fi

echo "[3/4] Installing dependencies..."
"$VENV_PY" -m pip install --upgrade pip
"$VENV_PY" -m pip install -r requirements.txt

echo "[4/4] Installation complete."
echo "You can now start the app by double-clicking \"Run Calendar App.command\"."
echo "This installer also removed macOS quarantine from the project when possible."
read -r -p "Press Enter to close..."
