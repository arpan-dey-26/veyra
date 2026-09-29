@echo off
REM Deployed smoke test (asks for the demo staff password; nothing is stored).
cd /d "%~dp0..\.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0smoke.ps1" %*
echo.
pause
