[CmdletBinding()]
param(
    [string]$Repository = "wly-ysu/web-bridge-codex",
    [string]$DownloadUrl = "",
    [switch]$NonInteractive,
    [switch]$AcceptAiProfile,
    [switch]$AcceptManagedRuntimeReplacement,
    [switch]$SkipBrowserLaunch
)

$ErrorActionPreference = "Stop"
$root = Join-Path ([IO.Path]::GetTempPath()) ("web-bridge-codex-bootstrap-" + [guid]::NewGuid().ToString("N"))
try {
    New-Item -ItemType Directory -Path (Join-Path $root "scripts\release"), (Join-Path $root "scripts\windows") -Force | Out-Null
    Invoke-WebRequest -Uri "https://raw.githubusercontent.com/$Repository/main/scripts/release/install-windows.ps1" -OutFile (Join-Path $root "scripts\release\install-windows.ps1")
    Invoke-WebRequest -Uri "https://raw.githubusercontent.com/$Repository/main/scripts/windows/BridgeInstaller.Common.psm1" -OutFile (Join-Path $root "scripts\windows\BridgeInstaller.Common.psm1")
    & (Join-Path $root "scripts\release\install-windows.ps1") -Repository $Repository -DownloadUrl $DownloadUrl -NonInteractive:$NonInteractive -AcceptAiProfile:$AcceptAiProfile -AcceptManagedRuntimeReplacement:$AcceptManagedRuntimeReplacement -SkipBrowserLaunch:$SkipBrowserLaunch
    exit $LASTEXITCODE
} finally {
    Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
}
