[CmdletBinding()]
param(
    [switch]$PurgeUserData
)

$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "BridgeInstaller.Common.psm1") -Force
$paths = Get-BridgePaths
Set-BridgeMcpRegistration -Remove | Out-Null
Set-BridgeWebFirstRule -Remove
if ($PurgeUserData) {
    if (Test-Path -LiteralPath $paths.Root) { Remove-Item -LiteralPath $paths.Root -Recurse -Force }
    Write-Host "Bridge application, configuration, logs, and dedicated Chrome profile removed."
} else {
    foreach ($name in @("app", "runtime", "bin")) {
        $target = $paths[$name.Substring(0,1).ToUpper() + $name.Substring(1)]
        if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
    }
    Write-Host "Bridge application removed. Configuration, logs, and dedicated Chrome profile were kept."
}
Write-Host "Restart Codex to unload the MCP server."
