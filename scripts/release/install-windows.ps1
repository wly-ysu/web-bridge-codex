[CmdletBinding()]
param(
    [string]$Repository = "wly-ysu/web-bridge-codex",
    [string]$ArtifactPath = "",
    [string]$DownloadUrl = "",
    [string]$ChromePath = "",
    [switch]$NonInteractive,
    [switch]$AcceptAiProfile,
    [switch]$SkipBrowserLaunch
)

$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "..\windows\BridgeInstaller.Common.psm1") -Force

try {
    $null = Migrate-LegacyBridgeInstall
    $paths = Get-BridgePaths
    foreach ($path in @($paths.Root, $paths.Config, $paths.Logs, $paths.State, $paths.Bin)) { Ensure-BridgeDirectory $path }
    $chrome = if ($ChromePath) { $ChromePath } else { Install-BridgeChromeIfNeeded }
    if (-not (Test-Path -LiteralPath $chrome)) { throw "Chrome executable was not found: $chrome" }
    if ($NonInteractive -and -not $AcceptAiProfile) { throw "Non-interactive installation requires -AcceptAiProfile." }
    if (-not $NonInteractive -and -not $AcceptAiProfile -and (Read-Host "Create or reuse dedicated AI Chrome Profile at $($paths.Profile)? [y/N]") -notmatch '^(?i)y(?:es)?$') {
        throw "AI Chrome Profile creation was cancelled."
    }
    if (-not (Test-Path -LiteralPath $paths.Profile)) { Ensure-BridgeDirectory $paths.Profile }

    $temporary = Join-Path ([IO.Path]::GetTempPath()) ("web-bridge-codex-release-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $temporary -Force | Out-Null
    try {
        $archive = if ($ArtifactPath) { (Resolve-Path -LiteralPath $ArtifactPath).Path } else { Join-Path $temporary "web-bridge-codex-windows-x64.zip" }
        if (-not $ArtifactPath) {
            $url = if ($DownloadUrl) { $DownloadUrl } else { "https://github.com/$Repository/releases/latest/download/web-bridge-codex-windows-x64.zip" }
            Invoke-WebRequest -Uri $url -OutFile $archive
        }
        Expand-Archive -LiteralPath $archive -DestinationPath $temporary -Force
        $package = Join-Path $temporary "web-bridge-codex-windows-x64"
        if (-not (Test-Path -LiteralPath (Join-Path $package "web-bridge-codex.exe")) -or -not (Test-Path -LiteralPath (Join-Path $package "config.example.yaml"))) {
            throw "Invalid Windows release archive."
        }
        if ((Get-BridgeServerProcesses).Count -gt 0) { throw "Close Codex before upgrading web-bridge-codex." }
        if (Test-Path -LiteralPath $paths.App) { Remove-Item -LiteralPath $paths.App -Recurse -Force }
        Move-Item -LiteralPath $package -Destination $paths.App
    } finally {
        Remove-Item -LiteralPath $temporary -Recurse -Force -ErrorAction SilentlyContinue
    }

    Write-BridgeConfig -SourceDir $paths.App -ChromePath $chrome
    $launcher = Join-Path $paths.App "web-bridge-codex.exe"
    & $launcher --configure-user --codex-config $paths.CodexConfig --agents-file $paths.CodexRules --launcher $launcher --log-path (Join-Path $paths.Logs "bridge_mcp.log")
    if ($LASTEXITCODE -ne 0) { throw "Compiled bridge could not configure Codex." }
    if ((Test-Path (Join-Path $paths.App "server.py")) -or (Test-Path (Join-Path $paths.App "adapters")) -or (Test-Path (Join-Path $paths.App "core")) -or (Test-Path (Join-Path $paths.App "tools")) -or (Test-Path (Join-Path $paths.App "deploy"))) {
        throw "Release installation contains project source files and was rejected."
    }
    if (-not $SkipBrowserLaunch) { Start-Process -FilePath $chrome -ArgumentList "--user-data-dir=$($paths.Profile)", "--new-window", "https://chatgpt.com/" }
    Write-Output "WINDOWS_RELEASE_INSTALL_OK"
    Write-Output "install_root=$($paths.Root)"
    Write-Output "launcher=$launcher"
    Write-Output "next_action=Sign in to ChatGPT once in the dedicated profile, then restart Codex."
} catch {
    Write-Error "Release installation failed: $($_.Exception.Message)"
    exit 1
}
