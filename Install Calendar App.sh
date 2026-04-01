#!/bin/bash
set -euo pipefail

# Run from the project directory so relative paths are stable.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PACKAGE_MANAGER=""
PY_CMD=""
SYSTEM_INSTALL_ATTEMPTED=0

pause_before_exit() {
    local exit_code="${1:-0}"
    if [[ -t 0 ]]; then
        read -r -p "Press Enter to close..." _
    fi
    exit "$exit_code"
}

find_python_command() {
    PY_CMD=""
    if command -v python3 >/dev/null 2>&1; then
        PY_CMD="python3"
    elif command -v python >/dev/null 2>&1; then
        PY_CMD="python"
    fi

    if [[ -n "$PY_CMD" ]] && ! "$PY_CMD" -c 'import sys; raise SystemExit(0 if sys.version_info.major == 3 else 1)' >/dev/null 2>&1; then
        PY_CMD=""
    fi
}

detect_package_manager() {
    PACKAGE_MANAGER=""
    if command -v apt-get >/dev/null 2>&1; then
        PACKAGE_MANAGER="apt"
    elif command -v dnf >/dev/null 2>&1; then
        PACKAGE_MANAGER="dnf"
    elif command -v yum >/dev/null 2>&1; then
        PACKAGE_MANAGER="yum"
    elif command -v pacman >/dev/null 2>&1; then
        PACKAGE_MANAGER="pacman"
    fi
}

run_as_root() {
    if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
        "$@"
        return
    fi

    if command -v sudo >/dev/null 2>&1; then
        sudo "$@"
        return
    fi

    echo
    echo "Administrator access is needed to install missing system packages."
    echo "Re-run this installer with sudo, or install Python 3 + Tkinter manually."
    pause_before_exit 1
}

install_system_packages() {
    if [[ "$SYSTEM_INSTALL_ATTEMPTED" -eq 1 ]]; then
        return 0
    fi
    SYSTEM_INSTALL_ATTEMPTED=1

    detect_package_manager
    if [[ -z "$PACKAGE_MANAGER" ]]; then
        return 1
    fi

    echo
    echo "Missing Linux system packages were detected."
    case "$PACKAGE_MANAGER" in
        apt)
            echo "Attempting install with apt-get: python3 python3-venv python3-tk"
            run_as_root apt-get update
            run_as_root apt-get install -y python3 python3-venv python3-tk
            ;;
        dnf)
            echo "Attempting install with dnf: python3 python3-pip python3-tkinter"
            run_as_root dnf install -y python3 python3-pip python3-tkinter
            ;;
        yum)
            echo "Attempting install with yum: python3 python3-pip python3-tkinter"
            run_as_root yum install -y python3 python3-pip python3-tkinter
            ;;
        pacman)
            echo "Attempting install with pacman: python python-pip tk"
            run_as_root pacman -Sy --noconfirm python python-pip tk
            ;;
    esac

    find_python_command
    return 0
}

ensure_python_prerequisites() {
    find_python_command
    if [[ -z "$PY_CMD" ]]; then
        install_system_packages || true
        find_python_command
    fi

    if [[ -z "$PY_CMD" ]]; then
        echo
        echo "Python 3 was not found on this Linux system."
        echo "Install Python 3 and run this installer again."
        pause_before_exit 1
    fi

    if ! "$PY_CMD" -c 'import venv' >/dev/null 2>&1; then
        install_system_packages || true
    fi

    if ! "$PY_CMD" -c 'import tkinter' >/dev/null 2>&1; then
        install_system_packages || true
    fi

    if ! "$PY_CMD" -c 'import venv' >/dev/null 2>&1; then
        echo
        echo "The Python 'venv' module is still unavailable."
        echo "Install your distro's Python venv package and run this installer again."
        pause_before_exit 1
    fi

    if ! "$PY_CMD" -c 'import tkinter' >/dev/null 2>&1; then
        echo
        echo "Tkinter is still unavailable for Python 3."
        echo "Install your distro's Tkinter package and run this installer again."
        pause_before_exit 1
    fi
}

echo "[1/5] Preparing Linux launcher permissions..."
chmod +x "$SCRIPT_DIR"/*.sh 2>/dev/null || true

echo "[2/5] Checking Python 3 + Tkinter..."
ensure_python_prerequisites

echo "[3/5] Creating virtual environment..."
if [[ ! -x ".venv/bin/python3" && ! -x ".venv/bin/python" ]]; then
    rm -rf ".venv"
    if ! "$PY_CMD" -m venv ".venv"; then
        install_system_packages || true
        rm -rf ".venv"
        if ! "$PY_CMD" -m venv ".venv"; then
            echo
            echo "Failed to create the virtual environment."
            echo "Make sure Python's venv support is installed, then run this installer again."
            pause_before_exit 1
        fi
    fi
fi

VENV_PY=".venv/bin/python3"
if [[ ! -x "$VENV_PY" ]]; then
    VENV_PY=".venv/bin/python"
fi
if [[ ! -x "$VENV_PY" ]]; then
    echo "Failed to locate the virtual environment Python executable."
    pause_before_exit 1
fi

echo "[4/5] Installing Python dependencies..."
"$VENV_PY" -m ensurepip --upgrade >/dev/null 2>&1 || true
"$VENV_PY" -m pip install --upgrade pip
"$VENV_PY" -m pip install -r requirements.txt

echo "[5/5] Installation complete."
echo "You can now start the app with ./Run\\ Calendar\\ App.sh"
echo "or by double-clicking \"Run Calendar App.sh\" in a Linux file manager."
pause_before_exit 0
