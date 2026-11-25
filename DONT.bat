@echo off
setlocal
cd /d "%~dp0"

echo OFFLINE LICENSE ISSUER
echo Use this only on the issuer computer with the private signing key installed.
echo.
set /p "FINGERPRINT=Enter the operator's 64-character machine fingerprint: "
if not defined FINGERPRINT (
    echo No fingerprint entered. Nothing was issued.
    goto :finish
)

set /p "LICENSE_OUTPUT=Output license file [operator_license.txt]: "
if not defined LICENSE_OUTPUT set "LICENSE_OUTPUT=operator_license.txt"

python source\security\license_issuer.py --fingerprint "%FINGERPRINT%" --output "%LICENSE_OUTPUT%"
set "APP_EXIT=%ERRORLEVEL%"
goto :pause_and_exit

:finish
set "APP_EXIT=2"

:pause_and_exit
echo.
pause
exit /b %APP_EXIT%
