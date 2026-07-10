[CmdletBinding()]
param(
    [switch]$ReinstallDependencies,
    [switch]$LaunchBrowser
)

$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "BridgeInstaller.Common.psm1") -Force
$paths = Get-BridgePaths
if (-not (Test-Path -LiteralPath $paths.App)) { throw "Bridge application is missing. Run install.ps1 again from the source checkout." }
foreach ($path in @($paths.Config, $paths.Logs, $paths.State, $paths.Profile, $paths.Bin)) { Ensure-BridgeDirectory $path }
Write-BridgeConfig -SourceDir $paths.App
if ($ReinstallDependencies) {
    $venvPython = Join-Path $paths.Runtime "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython)) { throw "The isolated Python runtime is missing. Run install.ps1 again." }
    & $venvPython -m pip install -r (Join-Path $paths.App "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "Dependency repair failed." }
}
Set-BridgeMcpRegistration | Out-Null
Set-BridgeWebFirstRule
if ($LaunchBrowser) { & (Join-Path $PSScriptRoot "launch-web-profile.ps1") }
Write-Host "Repair completed. Restart Codex to reload the MCP registration."
