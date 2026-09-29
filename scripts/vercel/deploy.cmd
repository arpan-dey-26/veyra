@echo off
REM Deploy VEYRA to Vercel production: API (apps/api) first, then the web app (repo root,
REM project root directory apps/web). See docs/deployment.md for the one-time setup.
cd /d "%~dp0..\.."
cd apps\api
call npx --yes vercel@latest deploy --prod --yes
if errorlevel 1 exit /b 1
cd ..\..
call npx --yes vercel@latest deploy --prod --yes
