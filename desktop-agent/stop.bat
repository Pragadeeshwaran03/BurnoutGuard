@echo off
:: ============================================================
:: stop.bat — Kill the BurnoutGuard Desktop Agent
:: ============================================================
setlocal

set "AGENT_DIR=%~dp0"
set "PID_FILE=%AGENT_DIR%agent.pid"

echo Stopping BurnoutGuard Desktop Agent...

:: Try reading PID from agent.pid first (cleanest method)
if exist "%PID_FILE%" (
    set /p AGENT_PID=<"%PID_FILE%"
    if defined AGENT_PID (
        echo Sending stop signal to PID !AGENT_PID!...
        taskkill /PID !AGENT_PID! /F >nul 2>&1
        if errorlevel 1 (
            echo [WARN] Process !AGENT_PID! not found. It may have already stopped.
        ) else (
            echo Agent stopped (PID !AGENT_PID!).
        )
        del "%PID_FILE%" >nul 2>&1
        goto :done
    )
)

:: Fallback: kill all pythonw.exe processes running agent.py
echo (No PID file found — killing all pythonw.exe processes)
taskkill /IM pythonw.exe /F >nul 2>&1
if errorlevel 1 (
    echo No pythonw.exe process found. Agent may not be running.
) else (
    echo All pythonw.exe processes stopped.
)

:done
echo.
pause
endlocal
