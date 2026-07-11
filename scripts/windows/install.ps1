[CmdletBinding()]
param(
    [string]$SourceDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")),
    [switch]$SkipPythonInstall,
    [switch]$SkipBrowserLaunch,
    [switch]$AcceptAiProfile,
    [switch]$NonInteractive
)

$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "BridgeInstaller.Common.psm1") -Force

try {
    $migration = Migrate-LegacyBridgeInstall
    $paths = Get-BridgePaths
    foreach ($path in @($paths.Root, $paths.Config, $paths.Logs, $paths.State, $paths.Bin)) { Ensure-BridgeDirectory $path }
    $python = if ($SkipPythonInstall) { Get-BridgePython } else { Install-BridgePythonIfNeeded }
    if (-not $python) { throw "Python 3.11+ is required. Install it, then re-run this command." }
    $chrome = Install-BridgeChromeIfNeeded

    $profileExists = Test-Path -LiteralPath $paths.Profile
    if ($profileExists -and -not (Test-Path -LiteralPath $paths.Profile -PathType Container)) {
        throw "AI Chrome Profile path exists but is not a directory: $($paths.Profile)"
    }
    $profileAction = if ($profileExists) { "reuse the existing dedicated profile" } else { "create a new dedicated profile" }
    Write-Host ""
    Write-Host "Detected Google Chrome: $chrome"
    Write-Host "AI Chrome Profile: $($paths.Profile)"
    Write-Host "Profile action: $profileAction"
    Write-Host "This Profile is isolated from your normal Chrome data and will never be reset by the installer."
    if ($NonInteractive) {
        if (-not $AcceptAiProfile) {
            throw "Non-interactive installation requires -AcceptAiProfile before a dedicated AI Chrome Profile can be created or reused."
        }
    } elseif (-not $AcceptAiProfile) {
        $answer = Read-Host "Create or use this dedicated AI Chrome Profile? [y/N]"
        if ($answer -notmatch '^(?i)y(?:es)?$') {
            throw "AI Chrome Profile creation was cancelled by the user. No browser profile was created or changed."
        }
    }
    if (-not $profileExists) { Ensure-BridgeDirectory $paths.Profile }

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
    $webFirstRule = Set-BridgeWebFirstRule
    $version = (Get-Content -LiteralPath (Join-Path $SourceDir "VERSION") -Raw).Trim()
    Write-Host ""
    Write-Host "web-bridge-codex $version installed for this Windows user."
    Write-Host "Legacy migration: $migration"
    Write-Host "MCP registration: $registration"
    Write-Host "Web-First rule: $webFirstRule"
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

