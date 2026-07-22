[CmdletBinding()]
param(
    [string]$Repository = "wly-ysu/web-bridge-codex",
    [string]$ArtifactPath = "",
    [string]$DownloadUrl = "",
    [string]$ChromePath = "",
    [switch]$NonInteractive,
    [switch]$AcceptAiProfile,
    [switch]$AcceptManagedRuntimeReplacement,
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
        $existingLauncher = Join-Path $paths.App "web-bridge-codex.exe"
        if ((Test-Path -LiteralPath $existingLauncher) -and (Test-Path -LiteralPath $paths.ConfigFile)) {
            try {
                & $existingLauncher --shutdown-broker --config $paths.ConfigFile 2>$null | ForEach-Object { Write-Host $_ }
            } catch {
                Write-Host "Existing runtime does not support graceful broker shutdown; continuing with the process safety check."
            }
            $brokerStopDeadline = (Get-Date).AddSeconds(10)
            while ((Get-Date) -lt $brokerStopDeadline -and @(
                Get-BridgeServerProcesses | Where-Object { "$($_.CommandLine)" -match '--browser-broker' }
            ).Count -gt 0) {
                Start-Sleep -Milliseconds 200
            }
        }
        if ((Get-BridgeServerProcesses).Count -gt 0) { throw "Close Codex before upgrading web-bridge-codex." }
        if (Test-Path -LiteralPath $paths.App) {
            Write-Host "web-bridge-codex upgrade will replace only this managed runtime:"
            Write-Host "  REPLACE: $($paths.App)"
            Write-Host "  PRESERVE: $($paths.Profile)"
            Write-Host "  PRESERVE: $($paths.CodexConfig) except the web-bridge-codex MCP section"
            Write-Host "  PRESERVE: all other Codex MCP entries, user projects, and system Chrome"
            if ($NonInteractive -and -not $AcceptManagedRuntimeReplacement) {
                throw "Non-interactive upgrade requires -AcceptManagedRuntimeReplacement."
            }
            if (-not $NonInteractive -and -not $AcceptManagedRuntimeReplacement -and (Read-Host "Replace only the managed runtime shown above? [y/N]") -notmatch '^(?i)y(?:es)?$') {
                throw "Managed runtime replacement was cancelled; no files were deleted."
            }
            try {
                Remove-Item -LiteralPath $paths.App -Recurse -Force -ErrorAction Stop
            } catch {
                throw "Cannot replace the existing web-bridge-codex runtime because a file is still in use. Completely exit every Codex window, wait a few seconds for its MCP process to stop, then rerun this installer. Original error: $($_.Exception.Message)"
            }
        }
        Move-Item -LiteralPath $package -Destination $paths.App
    } finally {
        Remove-Item -LiteralPath $temporary -Recurse -Force -ErrorAction SilentlyContinue
    }

    Write-BridgeConfig -SourceDir $paths.App -ChromePath $chrome
    $launcher = Join-Path $paths.App "web-bridge-codex.exe"
    if (Test-Path -LiteralPath $paths.ConfigFile) { Backup-BridgeFile $paths.ConfigFile | Out-Null }
    & $launcher --migrate-managed-config --config $paths.ConfigFile
    if ($LASTEXITCODE -ne 0) { throw "Bridge managed config policy migration failed; Codex was not changed." }
    & $launcher --validate-config --config $paths.ConfigFile
    if ($LASTEXITCODE -ne 0) {
        Write-Host "CONFIG_REBUILT: existing bridge config failed validation; rebuilding from the current template."
        Write-BridgeConfig -SourceDir $paths.App -ChromePath $chrome -ForceRebuild
        & $launcher --validate-config --config $paths.ConfigFile
        if ($LASTEXITCODE -ne 0) { throw "Bridge config validation failed after rebuild; Codex was not changed." }
    }
    & $launcher --configure-user --config $paths.ConfigFile --codex-config $paths.CodexConfig --agents-file $paths.CodexRules --launcher $launcher --log-path (Join-Path $paths.Logs "bridge_mcp.log")
    if ($LASTEXITCODE -ne 0) { throw "Compiled bridge could not configure Codex." }
    if ((Test-Path (Join-Path $paths.App "server.py")) -or (Test-Path (Join-Path $paths.App "adapters")) -or (Test-Path (Join-Path $paths.App "core")) -or (Test-Path (Join-Path $paths.App "tools")) -or (Test-Path (Join-Path $paths.App "deploy"))) {
        throw "Release installation contains project source files and was rejected."
    }
    if (-not $SkipBrowserLaunch) { Start-Process -FilePath $chrome -ArgumentList "--user-data-dir=$($paths.Profile)", "--new-window", "https://chatgpt.com/" }
    @{ product = "web-bridge-codex"; schema_version = 2; managed_runtime = @($paths.App); preserved = @($paths.Profile); installed_at = (Get-Date).ToUniversalTime().ToString("o") } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $paths.State "install-manifest.json") -Encoding utf8
    Write-Output "INSTALL_OK_RESTART_CODEX"
    Write-Output "install_root=$($paths.Root)"
    Write-Output "launcher=$launcher"
    Write-Output "next_action=Sign in to ChatGPT once in the dedicated profile, then restart Codex."
} catch {
    Write-Error "Release installation failed: $($_.Exception.Message)"
    exit 1
}
