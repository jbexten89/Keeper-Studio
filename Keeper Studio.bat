@echo off
REM Double-click this to open Keeper Studio.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Keeper Studio is not set up yet.
  echo Double-click Setup.bat first, then try again.
  echo.
  pause
  exit /b 1
)
REM pythonw runs without leaving a console window behind.
start "" ".venv\Scripts\pythonw.exe" "%~dp0run_studio.py"
