@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
if not exist "%~dp0TextureStudio.vbs" (
  echo Extract ALL files from the ZIP before running Texture Studio.
  pause
  exit /b 1
)
"%SystemRoot%\System32\wscript.exe" "%~dp0TextureStudio.vbs"
exit /b %errorlevel%
