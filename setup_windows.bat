@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
title Texture Studio - Setup
if not exist "windows_env.bat" goto incomplete
call "%~dp0windows_env.bat"
if not exist "requirements-dev.txt" goto incomplete
if not exist "texture_studio\ui.py" goto incomplete
echo Environment location: %TS_VENV%
if exist "%TS_VENV%\Scripts\python.exe" goto validate

echo Looking for 64-bit Python 3.11, 3.12 or 3.13...
for %%V in (3.12 3.11 3.13) do (
  py -%%V -c "import struct,sys; sys.exit(not (struct.calcsize('P') == 8 and (3,11) <= sys.version_info[:2] < (3,14)))" >nul 2>&1
  if not errorlevel 1 (
    py -%%V -m venv "%TS_VENV%"
    if errorlevel 1 goto failed
    goto validate
  )
)
python -c "import struct,sys; sys.exit(not (struct.calcsize('P') == 8 and (3,11) <= sys.version_info[:2] < (3,14)))" >nul 2>&1
if errorlevel 1 goto missing_python
python -m venv "%TS_VENV%"
if errorlevel 1 goto failed

:validate
"%TS_VENV%\Scripts\python.exe" -c "import struct,sys; print(sys.version); sys.exit(not (struct.calcsize('P') == 8 and (3,11) <= sys.version_info[:2] < (3,14)))"
if errorlevel 1 goto incompatible
if not exist logs mkdir logs
echo Installing dependencies and running tests. This may take several minutes.
echo Detailed progress is saved to logs\setup.log
call :install_steps > "logs\setup.log" 2>&1
set "TS_EXIT=%errorlevel%"
type "logs\setup.log"
if not "%TS_EXIT%"=="0" goto failed
echo.
echo Setup completed. Double-click TextureStudio.vbs to open the app without a console.
pause
exit /b 0

:install_steps
"%TS_VENV%\Scripts\python.exe" -m pip --disable-pip-version-check install -r requirements-dev.txt
if errorlevel 1 exit /b 1
set "QT_QPA_PLATFORM=offscreen"
"%TS_VENV%\Scripts\python.exe" -m pytest -q
exit /b %errorlevel%

:missing_python
echo Install 64-bit Python 3.12 from https://www.python.org/downloads/windows/
echo Include the Python Launcher and Add Python to PATH, then run setup again.
echo These pinned dependencies support Python 3.11 through 3.13, not 3.14.
pause
exit /b 1

:incompatible
echo The existing environment uses an unsupported Python or a 32-bit interpreter.
echo Rename this directory to preserve it: %TS_VENV%
echo Then install 64-bit Python 3.12 and run setup again.
pause
exit /b 1

:incomplete
echo Extract ALL files from the ZIP before running setup.
echo Do not run this script inside the ZIP viewer.
pause
exit /b 1

:failed
echo.
echo Setup failed. Send the error above or logs\setup.log for diagnosis.
pause
exit /b 1
