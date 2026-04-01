"""Builds a standalone student-facing release package for the current platform."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path


APP_NAME = "Desktop Calendar"
ENTRYPOINT = "calendar_app.py"
ROOT_DIR = Path(__file__).resolve().parent
BUILD_ROOT = ROOT_DIR / "build" / "student_release"
DIST_ROOT = ROOT_DIR / "dist" / "student_release"
RELEASE_ROOT = ROOT_DIR / "release"


def current_platform_key() -> str:
    """Returns the normalized platform key used by the release builder."""
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def current_platform_label() -> str:
    """Returns a human-readable platform label for archive naming."""
    return {
        "windows": "Windows",
        "macos": "macOS",
        "linux": "Linux",
    }[current_platform_key()]


def ensure_pyinstaller_available() -> None:
    """Fails fast with a clear message when PyInstaller is not installed."""
    if importlib.util.find_spec("PyInstaller") is not None:
        return
    raise SystemExit(
        "PyInstaller is not installed in this Python environment.\n"
        "Run: python -m pip install -r requirements-build.txt"
    )


def clean_path(target: Path) -> None:
    """Removes an existing file or directory tree."""
    if target.is_dir():
        shutil.rmtree(target)
    elif target.exists():
        target.unlink()


def ensure_clean_dir(target: Path) -> None:
    """Creates an empty directory."""
    clean_path(target)
    target.mkdir(parents=True, exist_ok=True)


def run_command(command: list[str]) -> None:
    """Runs a subprocess from the repository root while echoing the command."""
    print("+", " ".join(f'"{part}"' if " " in part else part for part in command))
    subprocess.run(command, cwd=ROOT_DIR, check=True)


def write_text_file(target: Path, content: str) -> None:
    """Writes UTF-8 text with platform-appropriate newlines for shell scripts."""
    newline = "\r\n" if target.suffix == ".bat" else "\n"
    normalized = textwrap.dedent(content).lstrip("\n").rstrip() + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline=newline) as handle:
        handle.write(normalized)


def make_executable(target: Path) -> None:
    """Marks a generated Unix shell script as executable when supported."""
    if current_platform_key() == "windows":
        return
    target.chmod(target.stat().st_mode | 0o111)


def build_with_pyinstaller(platform_key: str) -> Path:
    """Builds the standalone app bundle for the current platform."""
    dist_dir = DIST_ROOT / platform_key
    work_dir = BUILD_ROOT / platform_key / "work"
    spec_dir = BUILD_ROOT / platform_key / "spec"
    ensure_clean_dir(dist_dir)
    ensure_clean_dir(work_dir)
    ensure_clean_dir(spec_dir)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onedir",
        f"--name={APP_NAME}",
        f"--distpath={dist_dir}",
        f"--workpath={work_dir}",
        f"--specpath={spec_dir}",
        "--collect-all=certifi",
        "--collect-all=selenium",
        ENTRYPOINT,
    ]
    if platform_key == "macos":
        command.insert(-1, "--osx-bundle-identifier=edu.school.desktopcalendar")

    run_command(command)

    if platform_key == "macos":
        bundle_path = dist_dir / f"{APP_NAME}.app"
    else:
        bundle_path = dist_dir / APP_NAME

    if not bundle_path.exists():
        raise SystemExit(f"PyInstaller finished, but the built bundle was not found at {bundle_path}")
    return bundle_path


def release_notes(platform_key: str) -> str:
    """Returns short student-facing instructions bundled with each release."""
    platform_label = {
        "windows": "Windows",
        "macos": "macOS",
        "linux": "Linux",
    }[platform_key]
    extra_step = {
        "windows": 'Double-click "Install Desktop Calendar.bat".',
        "macos": 'Double-click "Install Desktop Calendar.command".',
        "linux": 'Run ./Install\\ Desktop\\ Calendar.sh after extracting the zip.',
    }[platform_key]
    launch_step = {
        "windows": 'Use the Desktop shortcut or double-click "Run Desktop Calendar.bat".',
        "macos": 'Open "Desktop Calendar.app" from Applications or double-click "Run Desktop Calendar.command".',
        "linux": 'Use your application menu entry or run ./Run\\ Desktop\\ Calendar.sh.',
    }[platform_key]
    return f"""\
    Desktop Calendar Student Release ({platform_label})

    This package already includes everything needed to run the app.
    Python is not required on the student's machine.

    Install:
    - {extra_step}

    Launch:
    - {launch_step}

    Saved calendar data is stored in the user's profile, so updating the app does not remove existing items.
    """


def windows_install_script() -> str:
    """Returns the Windows student installer wrapper."""
    return f"""
    @echo off
    setlocal EnableExtensions

    cd /d "%~dp0"

    set "APP_FOLDER={APP_NAME}"
    set "EXE_NAME={APP_NAME}.exe"
    set "SOURCE_DIR=%~dp0%APP_FOLDER%"
    set "INSTALL_DIR=%LocalAppData%\\Programs\\{APP_NAME}"
    set "START_MENU_DIR=%AppData%\\Microsoft\\Windows\\Start Menu\\Programs\\{APP_NAME}"
    set "START_MENU_LAUNCHER=%START_MENU_DIR%\\{APP_NAME}.bat"
    set "START_MENU_UNINSTALLER=%START_MENU_DIR%\\Uninstall {APP_NAME}.bat"
    set "DESKTOP_DIR=%USERPROFILE%\\Desktop"
    set "DESKTOP_LAUNCHER=%DESKTOP_DIR%\\{APP_NAME}.bat"
    set "INSTALLED_EXE=%INSTALL_DIR%\\%EXE_NAME%"
    set "INSTALLED_UNINSTALLER=%INSTALL_DIR%\\Uninstall {APP_NAME}.bat"

    for /f "delims=" %%I in ('powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"') do set "DESKTOP_DIR=%%I"
    set "DESKTOP_LAUNCHER=%DESKTOP_DIR%\\{APP_NAME}.bat"

    if not exist "%SOURCE_DIR%\\%EXE_NAME%" (
        echo Packaged app files were not found in "%SOURCE_DIR%".
        echo Extract the full zip before running this installer.
        echo.
        pause
        exit /b 1
    )

    echo [1/3] Installing app files...
    if exist "%INSTALL_DIR%" (
        rmdir /s /q "%INSTALL_DIR%"
        if exist "%INSTALL_DIR%" (
            echo Could not replace the existing installation.
            echo Close the app if it is open, then try again.
            echo.
            pause
            exit /b 1
        )
    )
    mkdir "%INSTALL_DIR%" >nul 2>&1
    robocopy "%SOURCE_DIR%" "%INSTALL_DIR%" /E /NFL /NDL /NJH /NJS /NP >nul
    if errorlevel 8 (
        echo Failed to copy the app files.
        echo.
        pause
        exit /b 1
    )

    echo [2/3] Creating launchers...
    if not exist "%START_MENU_DIR%" mkdir "%START_MENU_DIR%"
    copy /y "%~dp0Uninstall {APP_NAME}.bat" "%INSTALLED_UNINSTALLER%" >nul
    > "%DESKTOP_LAUNCHER%" (
        echo @echo off
        echo start "" "%%LocalAppData%%\\Programs\\{APP_NAME}\\{APP_NAME}.exe"
    )
    > "%START_MENU_LAUNCHER%" (
        echo @echo off
        echo start "" "%%LocalAppData%%\\Programs\\{APP_NAME}\\{APP_NAME}.exe"
    )
    > "%START_MENU_UNINSTALLER%" (
        echo @echo off
        echo call "%%LocalAppData%%\\Programs\\{APP_NAME}\\Uninstall {APP_NAME}.bat"
    )

    echo [3/3] Installation complete.
    echo {APP_NAME} will now open.
    start "" "%INSTALLED_EXE%"
    echo.
    pause
    exit /b 0
    """


def windows_run_script() -> str:
    """Returns a Windows launcher that prefers the installed copy."""
    return f"""
    @echo off
    setlocal EnableExtensions

    cd /d "%~dp0"

    set "INSTALLED_EXE=%LocalAppData%\\Programs\\{APP_NAME}\\{APP_NAME}.exe"
    set "PORTABLE_EXE=%~dp0{APP_NAME}\\{APP_NAME}.exe"

    if exist "%INSTALLED_EXE%" (
        start "" "%INSTALLED_EXE%"
        exit /b 0
    )

    if exist "%PORTABLE_EXE%" (
        start "" "%PORTABLE_EXE%"
        exit /b 0
    )

    echo {APP_NAME} was not found.
    echo Double-click "Install {APP_NAME}.bat" first.
    echo.
    pause
    exit /b 1
    """


def windows_uninstall_script() -> str:
    """Returns the Windows uninstaller for the packaged student release."""
    return f"""
    @echo off
    setlocal EnableExtensions EnableDelayedExpansion

    cd /d "%~dp0"

    set "INSTALL_DIR=%LocalAppData%\\Programs\\{APP_NAME}"
    set "START_MENU_DIR=%AppData%\\Microsoft\\Windows\\Start Menu\\Programs\\{APP_NAME}"
    set "START_MENU_LAUNCHER=%START_MENU_DIR%\\{APP_NAME}.bat"
    set "START_MENU_UNINSTALLER=%START_MENU_DIR%\\Uninstall {APP_NAME}.bat"
    set "DESKTOP_DIR=%USERPROFILE%\\Desktop"
    set "DESKTOP_LAUNCHER=%DESKTOP_DIR%\\{APP_NAME}.bat"
    set "DATA_FILE=%AppData%\\{APP_NAME}\\calendar_items.json"

    for /f "delims=" %%I in ('powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"') do set "DESKTOP_DIR=%%I"
    set "DESKTOP_LAUNCHER=%DESKTOP_DIR%\\{APP_NAME}.bat"

    echo [1/3] Removing installed app files...
    if exist "%INSTALL_DIR%" (
        rmdir /s /q "%INSTALL_DIR%"
        if exist "%INSTALL_DIR%" (
            echo Could not remove the installed app.
            echo Close the app if it is open, then try again.
            echo.
            pause
            exit /b 1
        )
        echo Removed "%INSTALL_DIR%".
    ) else (
        echo App files not found. Skipping.
    )

    echo [2/3] Removing launchers...
    if exist "%DESKTOP_LAUNCHER%" del /q "%DESKTOP_LAUNCHER%"
    if exist "%START_MENU_LAUNCHER%" del /q "%START_MENU_LAUNCHER%"
    if exist "%START_MENU_UNINSTALLER%" del /q "%START_MENU_UNINSTALLER%"
    if exist "%START_MENU_DIR%" rmdir "%START_MENU_DIR%" >nul 2>&1

    echo [3/3] Saved data cleanup (optional)
    if exist "%DATA_FILE%" (
        set /p REMOVE_DATA="Delete saved calendar data too? (y/N): "
        if /I "!REMOVE_DATA!"=="Y" (
            del /q "%DATA_FILE%"
            echo Removed saved calendar data.
        ) else (
            echo Kept saved calendar data.
        )
    ) else (
        echo No saved calendar data found. Skipping.
    )

    echo Uninstall complete.
    echo.
    pause
    exit /b 0
    """


def macos_install_script() -> str:
    """Returns the macOS installer wrapper for the packaged app."""
    return f"""
    #!/bin/bash
    set -euo pipefail

    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    cd "$SCRIPT_DIR"

    APP_BUNDLE="{APP_NAME}.app"
    SOURCE_APP="$SCRIPT_DIR/$APP_BUNDLE"
    TARGET_DIR="$HOME/Applications"
    TARGET_APP="$TARGET_DIR/$APP_BUNDLE"

    pause_before_exit() {{
        local exit_code="${{1:-0}}"
        if [[ -t 0 ]]; then
            read -r -p "Press Enter to close..." _
        fi
        exit "$exit_code"
    }}

    if [[ ! -d "$SOURCE_APP" ]]; then
        echo "The packaged app bundle was not found."
        echo "Extract the full zip before running this installer."
        pause_before_exit 1
    fi

    echo "[1/3] Installing the app to ~/Applications..."
    mkdir -p "$TARGET_DIR"
    rm -rf "$TARGET_APP"
    cp -R "$SOURCE_APP" "$TARGET_APP"
    chmod -R u+rwX "$TARGET_APP"

    echo "[2/3] Clearing macOS quarantine when possible..."
    if command -v xattr >/dev/null 2>&1; then
        xattr -dr com.apple.quarantine "$TARGET_APP" 2>/dev/null || true
    fi

    echo "[3/3] Installation complete."
    open "$TARGET_APP"
    pause_before_exit 0
    """


def macos_run_script() -> str:
    """Returns a macOS launcher that prefers the installed app bundle."""
    return f"""
    #!/bin/bash
    set -euo pipefail

    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    INSTALLED_APP="$HOME/Applications/{APP_NAME}.app"
    PORTABLE_APP="$SCRIPT_DIR/{APP_NAME}.app"

    pause_before_exit() {{
        local exit_code="${{1:-0}}"
        if [[ -t 0 ]]; then
            read -r -p "Press Enter to close..." _
        fi
        exit "$exit_code"
    }}

    if [[ -d "$INSTALLED_APP" ]]; then
        open "$INSTALLED_APP"
        exit 0
    fi
    if [[ -d "$PORTABLE_APP" ]]; then
        open "$PORTABLE_APP"
        exit 0
    fi

    echo "{APP_NAME}.app was not found."
    echo "Run ./Install\\ {APP_NAME}.command first."
    pause_before_exit 1
    """


def macos_uninstall_script() -> str:
    """Returns the macOS uninstaller for the packaged app."""
    return f"""
    #!/bin/bash
    set -euo pipefail

    TARGET_APP="$HOME/Applications/{APP_NAME}.app"
    DATA_FILE="$HOME/Library/Application Support/{APP_NAME}/calendar_items.json"

    pause_before_exit() {{
        local exit_code="${{1:-0}}"
        if [[ -t 0 ]]; then
            read -r -p "Press Enter to close..." _
        fi
        exit "$exit_code"
    }}

    echo "[1/2] Removing the installed app..."
    if [[ -d "$TARGET_APP" ]]; then
        rm -rf "$TARGET_APP"
        echo "Removed $TARGET_APP"
    else
        echo "App bundle not found. Skipping."
    fi

    echo "[2/2] Saved data cleanup (optional)"
    if [[ -f "$DATA_FILE" ]]; then
        read -r -p "Delete saved calendar data too? (y/N): " REMOVE_DATA
        if [[ "${{REMOVE_DATA:-N}}" =~ ^[Yy]$ ]]; then
            rm -f "$DATA_FILE"
            echo "Removed saved calendar data."
        else
            echo "Kept saved calendar data."
        fi
    else
        echo "No saved calendar data found. Skipping."
    fi

    echo "Uninstall complete."
    pause_before_exit 0
    """


def linux_install_script() -> str:
    """Returns the Linux installer wrapper for the packaged app folder."""
    return f"""
    #!/bin/bash
    set -euo pipefail

    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    cd "$SCRIPT_DIR"

    APP_FOLDER="{APP_NAME}"
    EXECUTABLE_NAME="{APP_NAME}"
    SOURCE_DIR="$SCRIPT_DIR/$APP_FOLDER"
    INSTALL_DIR="$HOME/.local/opt/desktop-calendar"
    EXECUTABLE_PATH="$INSTALL_DIR/$EXECUTABLE_NAME"
    DESKTOP_FILE="$HOME/.local/share/applications/desktop-calendar.desktop"
    DESKTOP_SHORTCUT="$HOME/Desktop/{APP_NAME}.desktop"

    pause_before_exit() {{
        local exit_code="${{1:-0}}"
        if [[ -t 0 ]]; then
            read -r -p "Press Enter to close..." _
        fi
        exit "$exit_code"
    }}

    if [[ ! -x "$SOURCE_DIR/$EXECUTABLE_NAME" ]]; then
        echo "The packaged app files were not found."
        echo "Extract the full zip before running this installer."
        pause_before_exit 1
    fi

    echo "[1/4] Installing app files..."
    rm -rf "$INSTALL_DIR"
    mkdir -p "$INSTALL_DIR"
    cp -R "$SOURCE_DIR"/. "$INSTALL_DIR"/
    chmod +x "$EXECUTABLE_PATH"

    echo "[2/4] Creating application launcher..."
    mkdir -p "$(dirname "$DESKTOP_FILE")"
    cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name={APP_NAME}
Exec="$EXECUTABLE_PATH"
Path="$INSTALL_DIR"
Terminal=false
Categories=Office;Education;
Icon=office-calendar
StartupNotify=true
EOF
    chmod +x "$DESKTOP_FILE"

    echo "[3/4] Creating Desktop shortcut when available..."
    if [[ -d "$HOME/Desktop" ]]; then
        cp "$DESKTOP_FILE" "$DESKTOP_SHORTCUT"
        chmod +x "$DESKTOP_SHORTCUT"
    fi

    echo "[4/4] Installation complete."
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true
    fi
    "$EXECUTABLE_PATH" >/dev/null 2>&1 &
    pause_before_exit 0
    """


def linux_run_script() -> str:
    """Returns a Linux launcher that prefers the installed copy."""
    return f"""
    #!/bin/bash
    set -euo pipefail

    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    INSTALLED_APP="$HOME/.local/opt/desktop-calendar/{APP_NAME}"
    PORTABLE_APP="$SCRIPT_DIR/{APP_NAME}/{APP_NAME}"

    pause_before_exit() {{
        local exit_code="${{1:-0}}"
        if [[ -t 0 ]]; then
            read -r -p "Press Enter to close..." _
        fi
        exit "$exit_code"
    }}

    if [[ -x "$INSTALLED_APP" ]]; then
        "$INSTALLED_APP" >/dev/null 2>&1 &
        exit 0
    fi
    if [[ -x "$PORTABLE_APP" ]]; then
        "$PORTABLE_APP"
        exit 0
    fi

    echo "{APP_NAME} was not found."
    echo "Run ./Install\\ {APP_NAME}.sh first."
    pause_before_exit 1
    """


def linux_uninstall_script() -> str:
    """Returns the Linux uninstaller for the packaged app."""
    return f"""
    #!/bin/bash
    set -euo pipefail

    INSTALL_DIR="$HOME/.local/opt/desktop-calendar"
    DESKTOP_FILE="$HOME/.local/share/applications/desktop-calendar.desktop"
    DESKTOP_SHORTCUT="$HOME/Desktop/{APP_NAME}.desktop"
    DATA_FILE="${{XDG_DATA_HOME:-$HOME/.local/share}}/{APP_NAME}/calendar_items.json"

    pause_before_exit() {{
        local exit_code="${{1:-0}}"
        if [[ -t 0 ]]; then
            read -r -p "Press Enter to close..." _
        fi
        exit "$exit_code"
    }}

    echo "[1/3] Removing installed app files..."
    if [[ -d "$INSTALL_DIR" ]]; then
        rm -rf "$INSTALL_DIR"
        echo "Removed $INSTALL_DIR"
    else
        echo "Installed app files not found. Skipping."
    fi

    echo "[2/3] Removing menu/Desktop launchers..."
    rm -f "$DESKTOP_FILE"
    rm -f "$DESKTOP_SHORTCUT"

    echo "[3/3] Saved data cleanup (optional)"
    if [[ -f "$DATA_FILE" ]]; then
        read -r -p "Delete saved calendar data too? (y/N): " REMOVE_DATA
        if [[ "${{REMOVE_DATA:-N}}" =~ ^[Yy]$ ]]; then
            rm -f "$DATA_FILE"
            echo "Removed saved calendar data."
        else
            echo "Kept saved calendar data."
        fi
    else
        echo "No saved calendar data found. Skipping."
    fi

    echo "Uninstall complete."
    pause_before_exit 0
    """


def assemble_windows_release(bundle_path: Path, release_dir: Path) -> None:
    """Copies the Windows bundle and writes the release wrapper scripts."""
    shutil.copytree(bundle_path, release_dir / APP_NAME)
    write_text_file(release_dir / f"Install {APP_NAME}.bat", windows_install_script())
    write_text_file(release_dir / f"Run {APP_NAME}.bat", windows_run_script())
    write_text_file(release_dir / f"Uninstall {APP_NAME}.bat", windows_uninstall_script())


def assemble_macos_release(bundle_path: Path, release_dir: Path) -> None:
    """Copies the macOS app bundle and writes the release wrapper scripts."""
    shutil.copytree(bundle_path, release_dir / bundle_path.name)
    install_path = release_dir / f"Install {APP_NAME}.command"
    run_path = release_dir / f"Run {APP_NAME}.command"
    uninstall_path = release_dir / f"Uninstall {APP_NAME}.command"
    write_text_file(install_path, macos_install_script())
    write_text_file(run_path, macos_run_script())
    write_text_file(uninstall_path, macos_uninstall_script())
    make_executable(install_path)
    make_executable(run_path)
    make_executable(uninstall_path)


def assemble_linux_release(bundle_path: Path, release_dir: Path) -> None:
    """Copies the Linux bundle and writes the release wrapper scripts."""
    shutil.copytree(bundle_path, release_dir / APP_NAME)
    install_path = release_dir / f"Install {APP_NAME}.sh"
    run_path = release_dir / f"Run {APP_NAME}.sh"
    uninstall_path = release_dir / f"Uninstall {APP_NAME}.sh"
    write_text_file(install_path, linux_install_script())
    write_text_file(run_path, linux_run_script())
    write_text_file(uninstall_path, linux_uninstall_script())
    make_executable(install_path)
    make_executable(run_path)
    make_executable(uninstall_path)


def assemble_release(platform_key: str, bundle_path: Path) -> tuple[Path, Path]:
    """Creates the student-ready release directory and zip archive."""
    release_dir = RELEASE_ROOT / f"{APP_NAME} {current_platform_label()}"
    ensure_clean_dir(release_dir)

    if platform_key == "windows":
        assemble_windows_release(bundle_path, release_dir)
    elif platform_key == "macos":
        assemble_macos_release(bundle_path, release_dir)
    else:
        assemble_linux_release(bundle_path, release_dir)

    write_text_file(release_dir / "README.txt", release_notes(platform_key))

    archive_base = RELEASE_ROOT / f"{APP_NAME} {current_platform_label()}"
    archive_path = archive_base.with_suffix(".zip")
    clean_path(archive_path)
    shutil.make_archive(str(archive_base), "zip", release_dir.parent, release_dir.name)
    return release_dir, archive_path


def main() -> None:
    """Builds and packages the student release for the current operating system."""
    platform_key = current_platform_key()
    ensure_pyinstaller_available()
    bundle_path = build_with_pyinstaller(platform_key)
    release_dir, archive_path = assemble_release(platform_key, bundle_path)
    print()
    print(f"Built {current_platform_label()} student release:")
    print(f"  Release folder: {release_dir}")
    print(f"  Zip archive:    {archive_path}")


if __name__ == "__main__":
    main()
