@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
title Texture Studio
if not exist "texture_studio\ui.py" goto incomplete
if not exist "windows_env.bat" goto incomplete
call "%~dp0windows_env.bat"
if not exist "%TS_VENV%\Scripts\python.exe" (
  echo Please run setup_windows.bat first.
  pause
  exit /b 1
)
if not exist logs mkdir logs
echo Starting Texture Studio. Keep this window open while the app runs.
"%TS_VENV%\Scripts\python.exe" -X faulthandler -u launch.py > "logs\startup-console.log" 2>&1
set "TS_EXIT=%errorlevel%"
if "%TS_EXIT%"=="0" exit /b 0
echo.
echo Texture Studio could not start. Error details:
type "logs\startup-console.log"
echo.
echo Please send logs\startup-console.log or a screenshot of this window.
pause
exit /b %TS_EXIT%

:incomplete
echo Extract ALL files from the ZIP before running this script.
echo Do not run it inside the ZIP viewer.
pause
exit /b 1
