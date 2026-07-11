@echo off
setlocal
where powershell.exe >nul 2>nul
if errorlevel 1 (
  echo ERROR: Windows PowerShell was not found.
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/wly-ysu/web-bridge-codex/main/scripts/windows/bootstrap.ps1 | iex"
exit /b %ERRORLEVEL%
