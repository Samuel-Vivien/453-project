@echo off
setlocal EnableExtensions

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo App dependencies are not installed yet.
    echo Double-click "Install Calendar App.bat" first.
    exit /b 1
)

if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "calendar_app.py"
) else (
    start "" ".venv\Scripts\python.exe" "calendar_app.py"
)

exit /b 0
