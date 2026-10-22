@echo off
rem Keep Qt's deeply nested package files away from long ZIP extraction paths.
set "TS_VENV=%USERPROFILE%\.texture-studio\venv"
if defined TEXTURE_STUDIO_VENV set "TS_VENV=%TEXTURE_STUDIO_VENV%"
exit /b 0
