@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
if not exist "windows_env.bat" exit /b 1
call "%~dp0windows_env.bat"
if not exist "%TS_VENV%\Scripts\python.exe" exit /b 1
set "TS_BUILD_ROOT=%USERPROFILE%\.texture-studio\packaging"
"%TS_VENV%\Scripts\python.exe" -m pytest -q
if errorlevel 1 exit /b 1
"%TS_VENV%\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --name TextureStudio --collect-submodules texture_studio --distpath "%TS_BUILD_ROOT%\dist" --workpath "%TS_BUILD_ROOT%\build" --specpath "%TS_BUILD_ROOT%" "%CD%\launch.py"
if errorlevel 1 exit /b 1
echo Built %TS_BUILD_ROOT%\dist\TextureStudio\TextureStudio.exe
echo Distribute the whole TextureStudio directory.
