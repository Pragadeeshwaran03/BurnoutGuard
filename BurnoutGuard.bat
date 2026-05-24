@echo off
:: ============================================================
:: BurnoutGuard Launcher
:: Double-click this to start the full application.
:: ============================================================
setlocal

set "ROOT=%~dp0"

:: Install launcher dependencies if needed (customtkinter, psutil, mouse)
echo Checking launcher dependencies...
pip show customtkinter >nul 2>&1 || pip install customtkinter psutil mouse --quiet
pip show psutil        >nul 2>&1 || pip install psutil mouse --quiet
pip show mouse         >nul 2>&1 || pip install mouse --quiet

:: Launch the desktop application
echo Starting BurnoutGuard Launcher...
start "" pythonw "%ROOT%launcher.py"

endlocal
