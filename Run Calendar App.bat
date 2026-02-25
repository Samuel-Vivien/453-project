@echo off
setlocal EnableExtensions

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo App dependencies are not installed yet.
    echo Double-click "Install Calendar App.bat" first.
    exit /b 1
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo Could not activate the virtual environment.
    exit /b 1
)

if exist ".venv\Scripts\pythonw.exe" (
    pythonw "calendar_app.py"
) else (
    python "calendar_app.py"
)

set "APP_EXIT_CODE=%errorlevel%"
call deactivate >nul 2>&1

exit /b %APP_EXIT_CODE%
