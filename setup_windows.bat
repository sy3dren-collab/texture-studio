@echo off
setlocal
cd /d "%~dp0"
py -3.11 -m venv .venv
if errorlevel 1 exit /b 1
.venv\Scripts\python -m pip install -r requirements-dev.txt
if errorlevel 1 exit /b 1
.venv\Scripts\python -m pytest -q
exit /b %errorlevel%
