@echo off
REM Double-click this once to install Keeper Studio.
REM Launches setup.ps1 with the execution policy bypassed, because Windows
REM blocks .ps1 files from running on double-click by default.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
if errorlevel 1 (
  echo.
  echo Setup did NOT finish. See setup-log.txt in this folder.
) else (
  echo.
  echo All good. Close this window, then double-click "Keeper Studio.bat"
)
echo.
pause
