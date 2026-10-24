@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
if not exist "windows_env.bat" exit /b 1
call "%~dp0windows_env.bat"
if not exist "%TS_VENV%\Scripts\python.exe" exit /b 1
set "TS_BUILD_ROOT=%USERPROFILE%\.texture-studio\packaging"
if defined TEXTURE_STUDIO_BUILD_ROOT set "TS_BUILD_ROOT=%TEXTURE_STUDIO_BUILD_ROOT%"
"%TS_VENV%\Scripts\python.exe" packaging\build_windows.py --output "%TS_BUILD_ROOT%"
if errorlevel 1 exit /b 1
echo Built and validated %TS_BUILD_ROOT%\release\TextureStudio.exe
echo The release directory contains a standalone EXE, ZIP, checksum and Windows validation report.
