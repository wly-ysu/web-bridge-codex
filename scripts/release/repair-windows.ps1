[CmdletBinding()]
param(
    [string]$ChromePath = ""
)

$ErrorActionPreference = "Stop"

function Find-Chrome([string]$RequestedPath) {
    if ($RequestedPath) { return $RequestedPath }
    foreach ($candidate in @(
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
        "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
    )) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) { return $candidate }
    }
    throw "Google Chrome was not found. Install Chrome, then run this repair again."
}

try {
    $root = Join-Path $env:LOCALAPPDATA "web-bridge-codex"
    $app = Join-Path $root "app"
    $launcher = Join-Path $app "web-bridge-codex.exe"
    $template = Join-Path $app "config.example.yaml"
    if (-not (Test-Path -LiteralPath $launcher) -or -not (Test-Path -LiteralPath $template)) {
        throw "web-bridge-codex is not installed. Run the release installer first."
    }

    $chrome = Find-Chrome $ChromePath
    if (-not (Test-Path -LiteralPath $chrome)) { throw "Chrome executable was not found: $chrome" }
    $configDir = Join-Path $root "config"
    $configPath = Join-Path $configDir "config.yaml"
    $profile = Join-Path $root "chrome-profile"
    New-Item -ItemType Directory -Force -Path $configDir, $profile | Out-Null

    $content = Get-Content -LiteralPath $template -Raw -Encoding utf8
    $content = [regex]::Replace($content, '(?m)^  user_data_dir:.*$', "  user_data_dir: `"$($profile.Replace('\', '/'))`"")
    $content = [regex]::Replace($content, '(?m)^  executable_path:.*$', "  executable_path: `"$($chrome.Replace('\', '/'))`"")
    Set-Content -LiteralPath $configPath -Value $content -Encoding utf8

    $codexHome = if ([string]::IsNullOrWhiteSpace($env:CODEX_HOME)) { Join-Path $env:USERPROFILE ".codex" } else { $env:CODEX_HOME }
    New-Item -ItemType Directory -Force -Path $codexHome | Out-Null
    & $launcher --configure-user --config $configPath --codex-config (Join-Path $codexHome "config.toml") --agents-file (Join-Path $codexHome "AGENTS.md") --launcher $launcher --log-path (Join-Path $root "logs\bridge_mcp.log")
    if ($LASTEXITCODE -ne 0) { throw "Compiled bridge could not reconfigure Codex." }

    Write-Output "WINDOWS_BRIDGE_REPAIR_OK"
    Write-Output "config_path=$configPath"
    Write-Output "next_action=Completely exit Codex, then reopen it to load the repaired MCP configuration."
} catch {
    Write-Error "Bridge repair failed: $($_.Exception.Message)"
    exit 1
}
