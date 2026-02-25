#!/bin/bash
set -euo pipefail

# Run from the project directory so relative paths are stable.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

VENV_ACTIVATE=".venv/bin/activate"
if [[ ! -f "$VENV_ACTIVATE" ]]; then
    echo "App dependencies are not installed yet."
    echo "Double-click \"Install Calendar App.command\" first."
    read -r -p "Press Enter to close..."
    exit 1
fi

source "$VENV_ACTIVATE"
trap 'deactivate >/dev/null 2>&1 || true' EXIT

python "calendar_app.py"
