@echo off
setlocal
cd /d "%~dp0"

python source\rendering\ffmpeg_engine.py
set "APP_EXIT=%ERRORLEVEL%"
echo.
pause
exit /b %APP_EXIT%
