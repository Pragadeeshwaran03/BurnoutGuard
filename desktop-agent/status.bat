@echo off
:: ============================================================
:: status.bat — Show whether BurnoutGuard Agent is running
:: ============================================================
setlocal EnableDelayedExpansion

set "AGENT_DIR=%~dp0"
set "PID_FILE=%AGENT_DIR%agent.pid"
set "LOG_FILE=%AGENT_DIR%agent.log"

echo ============================================================
echo  BurnoutGuard Desktop Agent — Status Check
echo ============================================================
echo.

:: Check PID file
if exist "%PID_FILE%" (
    set /p AGENT_PID=<"%PID_FILE%"
    tasklist /FI "PID eq !AGENT_PID!" 2>nul | find "python" >nul 2>&1
    if not errorlevel 1 (
        echo [RUNNING]  PID: !AGENT_PID!
    ) else (
        echo [STOPPED]  PID file found (!AGENT_PID!) but process is not running.
        echo            (You may need to delete agent.pid manually.)
    )
) else (
    :: Fallback: check if pythonw.exe is running
    tasklist /FI "IMAGENAME eq pythonw.exe" 2>nul | find "pythonw.exe" >nul 2>&1
    if not errorlevel 1 (
        echo [RUNNING]  pythonw.exe detected (no PID file — restart agent to fix)
    ) else (
        echo [STOPPED]  Agent is not running.
    )
)

echo.

:: Check Task Scheduler registration
schtasks /query /tn "BurnoutGuardAgent" >nul 2>&1
if errorlevel 1 (
    echo [AUTOSTART] NOT registered in Task Scheduler.
    echo             Run install.bat to enable auto-start on login.
) else (
    echo [AUTOSTART] Registered in Task Scheduler (auto-starts on login).
)

echo.

:: Show last 10 log lines
if exist "%LOG_FILE%" (
    echo Last 10 log lines from agent.log:
    echo ------------------------------------------------------------
    powershell -Command "Get-Content '%LOG_FILE%' -Tail 10"
) else (
    echo No agent.log found yet.
)

echo.
pause
endlocal
