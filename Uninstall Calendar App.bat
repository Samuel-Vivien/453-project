@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"

echo [1/3] Removing virtual environment...
if exist ".venv\" (
    rmdir /s /q ".venv"
    if exist ".venv\" (
        echo Failed to remove ".venv".
        echo.
        pause
        exit /b 1
    )
    echo Removed ".venv".
) else (
    echo ".venv" not found. Skipping.
)

echo [2/3] Removing Python cache folders...
for /d /r %%D in (__pycache__) do (
    if exist "%%D" rmdir /s /q "%%D" >nul 2>&1
)
del /s /q "*.pyc" >nul 2>&1
del /s /q "*.pyo" >nul 2>&1

echo [3/3] Local data cleanup (optional)
if exist "calendar_items.json" (
    set /p REMOVE_DATA="Delete calendar_items.json too? (y/N): "
    if /I "!REMOVE_DATA!"=="Y" (
        del /q "calendar_items.json"
        if exist "calendar_items.json" (
            echo Failed to remove "calendar_items.json".
            echo.
            pause
            exit /b 1
        )
        echo Removed "calendar_items.json".
    ) else (
        echo Kept "calendar_items.json".
    )
) else (
    echo "calendar_items.json" not found. Skipping.
)

echo Uninstall complete.
echo.
pause
exit /b 0
