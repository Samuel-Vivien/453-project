#!/bin/bash
set -euo pipefail

# Run from the project directory so relative paths are stable.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_VERSION="3.13.12"
PYTHON_INSTALLER_URL="https://www.python.org/ftp/python/${PYTHON_VERSION}/python-${PYTHON_VERSION}-macos11.pkg"
PYTHON_INSTALLER_PKG="${TMPDIR:-/tmp}/calendar-app-python-${PYTHON_VERSION}.pkg"
PY_CMD=""

pause_before_exit() {
    local exit_code="${1:-0}"
    if [[ -t 0 ]]; then
        read -r -p "Press Enter to close..." _
    fi
    exit "$exit_code"
}

find_python_command() {
    PY_CMD=""
    local candidates=()
    local candidate=""

    if command -v python3 >/dev/null 2>&1; then
        candidates+=("$(command -v python3)")
    fi
    if command -v python >/dev/null 2>&1; then
        candidates+=("$(command -v python)")
    fi

    candidates+=("/usr/local/bin/python3" "/opt/homebrew/bin/python3")

    shopt -s nullglob
    local framework_candidates=(/Library/Frameworks/Python.framework/Versions/*/bin/python3)
    shopt -u nullglob
    candidates+=("${framework_candidates[@]}")

    for candidate in "${candidates[@]}"; do
        if [[ -x "$candidate" ]] && "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info.major == 3 else 1)' >/dev/null 2>&1; then
            PY_CMD="$candidate"
            return 0
        fi
    done
    return 1
}

verify_python_modules() {
    [[ -n "$PY_CMD" ]] || return 1
    "$PY_CMD" -c 'import venv, tkinter' >/dev/null 2>&1
}

install_official_python() {
    if ! command -v curl >/dev/null 2>&1; then
        echo
        echo "curl is required to download Python automatically."
        echo "Install Python manually from https://www.python.org/downloads/macos/ and run this installer again."
        return 1
    fi

    echo "Downloading official Python ${PYTHON_VERSION} installer from python.org..."
    rm -f "$PYTHON_INSTALLER_PKG"
    if ! curl -L "$PYTHON_INSTALLER_URL" -o "$PYTHON_INSTALLER_PKG"; then
        echo
        echo "Failed to download Python from python.org."
        echo "Check your internet connection, then try again."
        echo "Manual download: https://www.python.org/downloads/macos/"
        rm -f "$PYTHON_INSTALLER_PKG"
        return 1
    fi

    echo "Installing Python. macOS may ask for your password..."
    if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
        if ! installer -pkg "$PYTHON_INSTALLER_PKG" -target / >/dev/null; then
            rm -f "$PYTHON_INSTALLER_PKG"
            echo
            echo "The Python installer did not complete successfully."
            echo "Manual download: https://www.python.org/downloads/macos/"
            return 1
        fi
    elif command -v sudo >/dev/null 2>&1; then
        if ! sudo installer -pkg "$PYTHON_INSTALLER_PKG" -target / >/dev/null; then
            rm -f "$PYTHON_INSTALLER_PKG"
            echo
            echo "The Python installer did not complete successfully."
            echo "Manual download: https://www.python.org/downloads/macos/"
            return 1
        fi
    else
        rm -f "$PYTHON_INSTALLER_PKG"
        echo
        echo "Administrator access is required to install Python automatically on macOS."
        echo "Manual download: https://www.python.org/downloads/macos/"
        return 1
    fi

    rm -f "$PYTHON_INSTALLER_PKG"
    find_python_command
}

echo "[0/5] Preparing macOS permissions..."
chmod +x "$SCRIPT_DIR"/*.command 2>/dev/null || true
if command -v xattr >/dev/null 2>&1; then
    xattr -dr com.apple.quarantine "$SCRIPT_DIR" 2>/dev/null || true
fi

echo "[1/5] Locating Python 3..."
if ! find_python_command; then
    echo
    echo "Python 3 was not found on this Mac."
    echo "Attempting to install official Python ${PYTHON_VERSION} from python.org..."
    if ! install_official_python || ! find_python_command; then
        echo "Install Python manually and run this installer again."
        pause_before_exit 1
    fi
fi

echo "[2/5] Verifying Python modules..."
if ! verify_python_modules; then
    echo
    echo "The detected Python is missing Tkinter or virtual environment support."
    echo "Attempting to install the official Python ${PYTHON_VERSION} build..."
    if ! install_official_python || ! verify_python_modules; then
        echo "Install Python manually from https://www.python.org/downloads/macos/ and run this installer again."
        pause_before_exit 1
    fi
fi

echo "[3/5] Creating virtual environment..."
if [[ ! -x ".venv/bin/python3" && ! -x ".venv/bin/python" ]]; then
    rm -rf ".venv"
    if ! "$PY_CMD" -m venv ".venv"; then
        echo
        echo "Failed to create the virtual environment."
        pause_before_exit 1
    fi
fi

VENV_PY=".venv/bin/python3"
if [[ ! -x "$VENV_PY" ]]; then
    VENV_PY=".venv/bin/python"
fi
if [[ ! -x "$VENV_PY" ]]; then
    echo "Failed to create virtual environment."
    pause_before_exit 1
fi

echo "[4/5] Installing dependencies..."
"$VENV_PY" -m ensurepip --upgrade >/dev/null 2>&1 || true
"$VENV_PY" -m pip install --upgrade pip
"$VENV_PY" -m pip install -r requirements.txt

echo "[5/5] Installation complete."
echo "You can now start the app by double-clicking \"Run Calendar App.command\"."
echo "This installer also removed macOS quarantine from the project when possible."
pause_before_exit 0
