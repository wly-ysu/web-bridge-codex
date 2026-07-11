[CmdletBinding()]
param(
    [string]$Repository = "wly-ysu/web-bridge-codex",
    [string]$Ref = "main",
    [switch]$SkipBrowserLaunch,
    [switch]$NonInteractive,
    [switch]$AcceptAiProfile
)

$ErrorActionPreference = "Stop"
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("pro_bridge_codex-" + [Guid]::NewGuid().ToString("N"))
try {
    New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
    $archive = Join-Path $tempRoot "source.zip"
    $url = "https://github.com/$Repository/archive/$([uri]::EscapeDataString($Ref)).zip"
    Write-Host "Downloading $Repository ($Ref)..."
    Invoke-WebRequest -Uri $url -OutFile $archive
    Expand-Archive -LiteralPath $archive -DestinationPath $tempRoot -Force
    $source = Get-ChildItem -LiteralPath $tempRoot -Directory | Where-Object { $_.Name -like "web-bridge-codex-*" } | Select-Object -First 1
    if (-not $source) { throw "The downloaded archive did not contain the bridge source." }
    & (Join-Path $source.FullName "scripts\windows\install.ps1") -SourceDir $source.FullName -SkipBrowserLaunch:$SkipBrowserLaunch -NonInteractive:$NonInteractive -AcceptAiProfile:$AcceptAiProfile
    exit $LASTEXITCODE
} finally {
    if (Test-Path -LiteralPath $tempRoot) { Remove-Item -LiteralPath $tempRoot -Recurse -Force }
}
