#!/bin/bash
set -euo pipefail

# Run from the project directory so relative paths are stable.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

chmod +x "$SCRIPT_DIR"/*.sh 2>/dev/null || true

VENV_PY=".venv/bin/python3"
if [[ ! -x "$VENV_PY" ]]; then
    VENV_PY=".venv/bin/python"
fi

if [[ ! -x "$VENV_PY" ]]; then
    echo "App dependencies are not installed yet."
    echo "Run ./Install\\ Calendar\\ App.sh first."
    if [[ -t 0 ]]; then
        read -r -p "Press Enter to close..." _
    fi
    exit 1
fi

"$VENV_PY" "calendar_app.py"
