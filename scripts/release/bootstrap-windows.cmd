@echo off
setlocal
set "BOOTSTRAP=%TEMP%\web-bridge-codex-release-bootstrap-%RANDOM%%RANDOM%.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/wly-ysu/web-bridge-codex/main/scripts/release/bootstrap-windows.ps1' -OutFile $env:BOOTSTRAP"
if errorlevel 1 exit /b %ERRORLEVEL%
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%BOOTSTRAP%" %*
set "EXITCODE=%ERRORLEVEL%"
del /q "%BOOTSTRAP%" >nul 2>nul
exit /b %EXITCODE%
