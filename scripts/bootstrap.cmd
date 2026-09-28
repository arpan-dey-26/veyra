@echo off
REM VEYRA Phase 0 bootstrap + verification. Double-click, or run from a terminal.
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0bootstrap.ps1" %*
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (echo VERIFICATION PASSED) else (echo VERIFICATION FAILED - see docs\phase-reports\phase-0-verification.log)
pause
exit /b %RC%
