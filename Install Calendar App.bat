@echo off
setlocal EnableExtensions

cd /d "%~dp0"

echo [1/4] Locating Python 3...
set "PY_CMD="
py -3 --version >nul 2>&1
if %errorlevel%==0 (
    set "PY_CMD=py -3"
) else (
    python --version >nul 2>&1
    if %errorlevel%==0 (
        set "PY_CMD=python"
    )
)

if not defined PY_CMD (
    echo.
    echo Python 3 was not found on this machine.
    echo Install Python 3 and run this installer again.
    exit /b 1
)

echo [2/4] Creating virtual environment...
if not exist ".venv\Scripts\python.exe" (
    call %PY_CMD% -m venv ".venv"
    if errorlevel 1 (
        echo Failed to create virtual environment.
        exit /b 1
    )
)

set "VENV_PY=.venv\Scripts\python.exe"

echo [3/4] Installing dependencies...
call "%VENV_PY%" -m pip install --upgrade pip
if errorlevel 1 (
    echo Failed to upgrade pip.
    exit /b 1
)

call "%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install requirements.
    exit /b 1
)

echo [4/4] Installation complete.
echo You can now start the app by double-clicking "Run Calendar App.bat".
exit /b 0
