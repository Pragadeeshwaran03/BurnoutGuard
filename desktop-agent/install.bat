@echo off
:: ============================================================
:: BurnoutGuard Desktop Agent — Windows Installer
:: Run this once per machine/user (no admin required).
:: ============================================================
setlocal EnableDelayedExpansion

set "AGENT_DIR=%~dp0"
set "TASK_NAME=BurnoutGuardAgent"
set "LOG=%AGENT_DIR%install.log"

echo ============================================================ > "%LOG%"
echo BurnoutGuard Desktop Agent Installer                        >> "%LOG%"
echo %date% %time%                                               >> "%LOG%"
echo ============================================================ >> "%LOG%"

echo.
echo ============================================================
echo  BurnoutGuard Desktop Agent Installer
echo ============================================================
echo.

:: ── Step 1: Check Python ─────────────────────────────────────
echo [1/4] Checking Python installation...
python --version >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not on PATH.
    echo Please install Python 3.9+ from https://python.org and try again.
    pause
    exit /b 1
)
echo       Python OK.

:: ── Step 2: Install dependencies ─────────────────────────────
echo [2/4] Installing Python dependencies...
pip install -r "%AGENT_DIR%requirements.txt" >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [ERROR] pip install failed. See install.log for details.
    pause
    exit /b 1
)
echo       Dependencies installed.

:: ── Step 3: Validate config.json ─────────────────────────────
echo [3/4] Checking config.json...
if not exist "%AGENT_DIR%config.json" (
    echo [ERROR] config.json not found in:
    echo         %AGENT_DIR%
    echo Please create it with your email and password.
    pause
    exit /b 1
)

findstr /C:"your-email@example.com" "%AGENT_DIR%config.json" >nul 2>&1
if not errorlevel 1 (
    echo.
    echo [WARNING] config.json still has placeholder credentials!
    echo           Please edit: %AGENT_DIR%config.json
    echo           Set your real email and password, then re-run this installer.
    echo.
    pause
)
echo       config.json OK.

:: ── Step 4: Register Windows Task Scheduler job ──────────────
echo [4/4] Registering startup task in Task Scheduler...

:: Prefer pythonw.exe (silent – no console window)
set "PYTHONW="
for /f "delims=" %%i in ('where pythonw 2^>nul') do (
    if "!PYTHONW!"=="" set "PYTHONW=%%i"
)
if "!PYTHONW!"=="" (
    for /f "delims=" %%i in ('where python 2^>nul') do (
        if "!PYTHONW!"=="" set "PYTHONW=%%i"
    )
)

:: Remove any old task first
schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1

:: Create the scheduled task
:: /sc ONLOGON  – runs when the current user logs in
:: /delay       – wait 1 minute after login before starting (format HH:MM)
:: /it          – interactive (runs in the user's session)
:: /rl LIMITED  – standard user privileges (no UAC prompt)
schtasks /create ^
  /tn "%TASK_NAME%" ^
  /tr "\"%PYTHONW%\" \"%AGENT_DIR%agent.py\"" ^
  /sc ONLOGON ^
  /delay 00:01 ^
  /it ^
  /rl LIMITED ^
  /f >> "%LOG%" 2>&1

if errorlevel 1 (
    echo.
    echo [WARNING] Could not create Task Scheduler job automatically.
    echo           The agent will NOT start automatically on login.
    echo           You can still run it manually — see below.
) else (
    echo.
    echo ============================================================
    echo  SUCCESS! Task "%TASK_NAME%" registered.
    echo  The agent will auto-start 1 minute after your next login.
    echo ============================================================
)

:: ── Done ─────────────────────────────────────────────────────
echo.
echo ── How to run right now ─────────────────────────────────────
echo   Visible (for testing):  python "%AGENT_DIR%agent.py"
echo   Silent (production):    start "" "%PYTHONW%" "%AGENT_DIR%agent.py"
echo.
echo ── How to stop ──────────────────────────────────────────────
echo   Run stop.bat, or open Task Manager and end pythonw.exe
echo.
echo ── Check logs at: %AGENT_DIR%agent.log
echo.
echo Install log: %LOG%
echo.
pause
endlocal
