@echo off
setlocal
cd /d "%~dp0"

python source\tools\recover.py
set "APP_EXIT=%ERRORLEVEL%"
echo.
pause
exit /b %APP_EXIT%
