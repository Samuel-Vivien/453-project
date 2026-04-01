@echo off
setlocal EnableExtensions

cd /d "%~dp0"

set "PYTHON_VERSION=3.13.12"
set "PYTHON_MAJOR_MINOR=313"
set "PYTHON_INSTALLER_URL=https://www.python.org/ftp/python/%PYTHON_VERSION%/python-%PYTHON_VERSION%-amd64.exe"
set "PYTHON_INSTALLER=%TEMP%\calendar-app-python-%PYTHON_VERSION%.exe"
set "PY_CMD="
set "PY_EXE="

if /I "%PROCESSOR_ARCHITECTURE%"=="ARM64" (
    set "PYTHON_INSTALLER_URL=https://www.python.org/ftp/python/%PYTHON_VERSION%/python-%PYTHON_VERSION%-arm64.exe"
) else if /I "%PROCESSOR_ARCHITECTURE%"=="x86" (
    if not defined PROCESSOR_ARCHITEW6432 (
        set "PYTHON_INSTALLER_URL=https://www.python.org/ftp/python/%PYTHON_VERSION%/python-%PYTHON_VERSION%.exe"
    )
)

echo [1/5] Locating Python 3...
call :find_python
if not defined PY_CMD if not defined PY_EXE (
    echo.
    echo Python 3 was not found on this machine.
    echo Attempting to download and install official Python %PYTHON_VERSION% from python.org...
    call :install_python
    if errorlevel 1 call :pause_and_exit 1
    call :find_python
)

if not defined PY_CMD if not defined PY_EXE (
    echo.
    echo Python appears to have been installed, but this window cannot find it yet.
    echo Close this window, then run "Install Calendar App.bat" one more time.
    call :pause_and_exit 1
)

echo [2/5] Verifying Python modules...
call :verify_python_modules
if errorlevel 1 (
    echo.
    echo The detected Python is missing Tkinter or virtual environment support.
    echo Attempting to install the official Python %PYTHON_VERSION% build...
    call :install_python
    if errorlevel 1 call :pause_and_exit 1
    call :find_python
    call :verify_python_modules
    if errorlevel 1 (
        echo.
        echo Python is installed, but Tkinter or venv is still unavailable.
        echo Install Python manually from https://www.python.org/downloads/windows/ and run this installer again.
        call :pause_and_exit 1
    )
)

echo [3/5] Creating virtual environment...
if not exist ".venv\Scripts\python.exe" (
    if exist ".venv\" rmdir /s /q ".venv"
    if defined PY_EXE (
        call "%PY_EXE%" -m venv ".venv"
    ) else (
        call %PY_CMD% -m venv ".venv"
    )
    if errorlevel 1 (
        echo Failed to create the virtual environment.
        call :pause_and_exit 1
    )
)

set "VENV_PY=.venv\Scripts\python.exe"

echo [4/5] Installing dependencies...
call "%VENV_PY%" -m ensurepip --upgrade >nul 2>&1
call "%VENV_PY%" -m pip install --upgrade pip
if errorlevel 1 (
    echo Failed to upgrade pip.
    call :pause_and_exit 1
)

call "%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install requirements.
    echo Check your internet connection and try again.
    call :pause_and_exit 1
)

echo [5/5] Installation complete.
echo You can now start the app by double-clicking "Run Calendar App.bat".
call :pause_and_exit 0

:find_python
set "PY_CMD="
set "PY_EXE="

py -3 --version >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=py -3"
    goto :eof
)

python --version >nul 2>&1
if not errorlevel 1 (
    python -c "import sys; raise SystemExit(0 if sys.version_info.major == 3 else 1)" >nul 2>&1
    if not errorlevel 1 (
        set "PY_CMD=python"
        goto :eof
    )
)

call :check_known_python_paths
goto :eof

:check_known_python_paths
for %%P in (
    "%LocalAppData%\Programs\Python\Python%PYTHON_MAJOR_MINOR%\python.exe"
    "%LocalAppData%\Programs\Python\Python%PYTHON_MAJOR_MINOR%-64\python.exe"
    "%LocalAppData%\Programs\Python\Python%PYTHON_MAJOR_MINOR%-32\python.exe"
    "%ProgramFiles%\Python%PYTHON_MAJOR_MINOR%\python.exe"
    "%ProgramFiles%\Python%PYTHON_MAJOR_MINOR%-64\python.exe"
    "%ProgramFiles(x86)%\Python%PYTHON_MAJOR_MINOR%-32\python.exe"
) do (
    if exist "%%~fP" (
        call "%%~fP" -c "import sys; raise SystemExit(0 if sys.version_info.major == 3 else 1)" >nul 2>&1
        if not errorlevel 1 (
            set "PY_EXE=%%~fP"
            goto :eof
        )
    )
)
goto :eof

:verify_python_modules
if defined PY_EXE (
    call "%PY_EXE%" -c "import venv, tkinter" >nul 2>&1
) else (
    call %PY_CMD% -c "import venv, tkinter" >nul 2>&1
)
exit /b %errorlevel%

:install_python
echo Downloading official Python installer...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference = 'SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%PYTHON_INSTALLER_URL%' -OutFile '%PYTHON_INSTALLER%'"
if errorlevel 1 (
    echo Failed to download Python from python.org.
    echo Check your internet connection, then try again.
    echo Manual download: https://www.python.org/downloads/windows/
    exit /b 1
)

echo Running Python installer...
"%PYTHON_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_tcltk=1 Include_test=0
if errorlevel 1 (
    del /q "%PYTHON_INSTALLER%" >nul 2>&1
    echo Python installation did not complete successfully.
    echo Manual download: https://www.python.org/downloads/windows/
    exit /b 1
)

del /q "%PYTHON_INSTALLER%" >nul 2>&1
exit /b 0

:pause_and_exit
echo.
pause
exit /b %~1
