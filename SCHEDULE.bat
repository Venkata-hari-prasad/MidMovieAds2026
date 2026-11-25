@echo off
setlocal
cd /d "%~dp0"

python source\main.py --mode filesystem
set "APP_EXIT=%ERRORLEVEL%"
echo.
pause
exit /b %APP_EXIT%
