[CmdletBinding()]
param(
    [string]$SourceDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")),
    [switch]$SkipPythonInstall,
    [switch]$SkipBrowserLaunch
)

$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "BridgeInstaller.Common.psm1") -Force

try {
    $paths = Get-BridgePaths
    foreach ($path in @($paths.Root, $paths.Config, $paths.Logs, $paths.State, $paths.Profile, $paths.Bin)) { Ensure-BridgeDirectory $path }
    $python = if ($SkipPythonInstall) { Get-BridgePython } else { Install-BridgePythonIfNeeded }
    if (-not $python) { throw "Python 3.11+ is required. Install it, then re-run this command." }
    $chrome = Install-BridgeChromeIfNeeded

    Copy-BridgeApplication -SourceDir $SourceDir
    Write-BridgeConfig -SourceDir $SourceDir

    $venvPython = Join-Path $paths.Runtime "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython)) {
        Write-Host "Creating isolated Python runtime..."
        & $python -m venv $paths.Runtime
        if ($LASTEXITCODE -ne 0) { throw "Could not create the isolated Python runtime." }
    }
    Write-Host "Installing bridge dependencies..."
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -r (Join-Path $paths.App "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "Could not install bridge dependencies." }

    $registration = Set-BridgeMcpRegistration
    Set-BridgeWebFirstRule
    $version = (Get-Content -LiteralPath (Join-Path $SourceDir "VERSION") -Raw).Trim()
    Write-Host ""
    Write-Host "pro_bridge_codex $version installed for this Windows user."
    Write-Host "MCP registration: $registration"
    Write-Host "Configuration: $($paths.ConfigFile)"
    Write-Host "Chrome profile: $($paths.Profile)"
    if (-not $SkipBrowserLaunch) {
        Write-Host "Opening the dedicated AI Chrome window now. Sign in to ChatGPT once in that window."
        & (Join-Path $PSScriptRoot "launch-web-profile.ps1")
    }
    Write-Host "Restart Codex after signing in to ChatGPT in the dedicated browser profile."
    Write-Host "Run scripts/windows/verify-install.ps1 to verify the local installation."
    Write-Host "Then call bridge_health_check, followed by ask_pro_architect with profile=fast."
} catch {
    Write-Error "Installation failed: $($_.Exception.Message)"
    exit 1
}
