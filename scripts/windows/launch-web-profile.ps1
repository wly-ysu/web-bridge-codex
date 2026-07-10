[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "BridgeInstaller.Common.psm1") -Force
$paths = Get-BridgePaths
$chrome = Find-BridgeChrome
if (-not $chrome) { throw "Google Chrome was not found. Install Chrome, then run this script again." }
if (-not (Test-Path -LiteralPath $paths.Profile -PathType Container)) {
    throw "Dedicated AI Chrome Profile does not exist: $($paths.Profile). Run install.ps1 and approve profile creation first."
}
Start-Process -FilePath $chrome -ArgumentList "--user-data-dir=`"$($paths.Profile)`"", "--new-window", "https://chatgpt.com/"
Write-Host "Dedicated AI Chrome profile opened. Sign in to ChatGPT there, then close/restart Codex."
