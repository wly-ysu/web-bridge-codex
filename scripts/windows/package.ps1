[CmdletBinding()]
param(
    [string]$Version = "dev",
    [string]$OutputDir = (Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..\..")) "packaging\output")
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$staging = Join-Path ([System.IO.Path]::GetTempPath()) ("pro_bridge_codex-package-" + [Guid]::NewGuid().ToString("N"))
try {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
    New-Item -ItemType Directory -Path $staging -Force | Out-Null
    $packageRoot = Join-Path $staging "pro_bridge_codex"
    New-Item -ItemType Directory -Path $packageRoot -Force | Out-Null
    $excluded = @(".git", "__pycache__", "logs", "runtime", "dist", "packaging", ".gptpro-browser", "browser_data", "config.yaml", "bridge_mcp.log", "bridge_launch_matrix.log")
    Get-ChildItem -LiteralPath $repositoryRoot -Force | Where-Object { $excluded -notcontains $_.Name } | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $packageRoot -Recurse -Force
    }
    $zip = Join-Path $OutputDir "pro_bridge_codex-windows-x64-v$Version.zip"
    if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
    Compress-Archive -LiteralPath $packageRoot -DestinationPath $zip -CompressionLevel Optimal
    $hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
    $checksumFile = Join-Path $OutputDir "SHA256SUMS.txt"
    Set-Content -LiteralPath $checksumFile -Value "$hash  $(Split-Path -Leaf $zip)" -Encoding ascii
    Write-Host "PACKAGE_OK"
    Write-Host "zip=$zip"
    Write-Host "checksum=$checksumFile"
} finally {
    if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
}
