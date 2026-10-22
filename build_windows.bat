@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe exit /b 1
.venv\Scripts\python -m pytest -q
if errorlevel 1 exit /b 1
.venv\Scripts\python -m PyInstaller --noconfirm --clean --windowed --name TextureStudio --collect-submodules texture_studio launch.py
if errorlevel 1 exit /b 1
echo Built dist\TextureStudio\TextureStudio.exe - distribute the whole TextureStudio directory.
