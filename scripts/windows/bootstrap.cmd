@echo off
setlocal
where powershell.exe >nul 2>nul
if errorlevel 1 (
  echo ERROR: Windows PowerShell was not found.
  exit /b 1
)
set "BOOTSTRAP=%TEMP%\pro_bridge_codex_bootstrap_%RANDOM%%RANDOM%.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/wly-ysu/web-bridge-codex/main/scripts/windows/bootstrap.ps1' -OutFile $env:BOOTSTRAP"
if errorlevel 1 exit /b %ERRORLEVEL%
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%BOOTSTRAP%" %*
set "EXITCODE=%ERRORLEVEL%"
del /q "%BOOTSTRAP%" >nul 2>nul
exit /b %EXITCODE%
