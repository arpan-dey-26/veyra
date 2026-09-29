@echo off
REM Link the Vercel CLI to your account (OAuth device flow; no token is stored in the repo).
cd /d "%~dp0..\.."
call npx --yes vercel@latest login
