@echo off
REM Builds a stand-alone "Keeper Studio" folder with Keeper Studio.exe in dist\.
REM Run Setup.bat first. GitHub also builds this automatically on every push
REM (Actions tab -> Build Windows app -> KeeperStudio-Windows).
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run Setup.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install --upgrade pyinstaller --quiet
".venv\Scripts\pyinstaller.exe" --noconfirm keeperstudio.spec
if errorlevel 1 (
  echo Build failed.
  pause
  exit /b 1
)
REM Config, models and colour presets live beside the exe so they stay editable.
copy /y config.yaml "dist\Keeper Studio\config.yaml" >nul
xcopy /y /e /i luts "dist\Keeper Studio\luts" >nul
xcopy /y /e /i models "dist\Keeper Studio\models" >nul
echo.
echo Built: dist\Keeper Studio\Keeper Studio.exe
pause
