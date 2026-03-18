#!/bin/bash
set -euo pipefail

# Run from the project directory so relative paths are stable.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

chmod +x "$SCRIPT_DIR"/*.command 2>/dev/null || true
if command -v xattr >/dev/null 2>&1; then
    xattr -dr com.apple.quarantine "$SCRIPT_DIR" 2>/dev/null || true
fi

echo "[1/3] Removing virtual environment..."
if [[ -d ".venv" ]]; then
    rm -rf ".venv"
    echo "Removed .venv"
else
    echo ".venv not found. Skipping."
fi

echo "[2/3] Removing Python cache folders..."
find . -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
find . -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete 2>/dev/null || true

echo "[3/3] Local data cleanup (optional)"
if [[ -f "calendar_items.json" ]]; then
    read -r -p "Delete calendar_items.json too? (y/N): " REMOVE_DATA
    if [[ "${REMOVE_DATA:-N}" =~ ^[Yy]$ ]]; then
        rm -f "calendar_items.json"
        echo "Removed calendar_items.json"
    else
        echo "Kept calendar_items.json"
    fi
else
    echo "calendar_items.json not found. Skipping."
fi

echo "Uninstall complete."
read -r -p "Press Enter to close..."
