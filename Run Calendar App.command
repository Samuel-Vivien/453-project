#!/bin/bash
set -euo pipefail

# Run from the project directory so relative paths are stable.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

VENV_PY=".venv/bin/python3"
if [[ ! -x "$VENV_PY" ]]; then
    VENV_PY=".venv/bin/python"
fi

if [[ ! -x "$VENV_PY" ]]; then
    echo "App dependencies are not installed yet."
    echo "Double-click \"Install Calendar App.command\" first."
    read -r -p "Press Enter to close..."
    exit 1
fi

"$VENV_PY" "calendar_app.py"
