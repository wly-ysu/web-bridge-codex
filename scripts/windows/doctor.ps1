[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "BridgeInstaller.Common.psm1") -Force
$paths = Get-BridgePaths
$python = Get-BridgePython
$venvPython = Join-Path $paths.Runtime "Scripts\python.exe"
$chrome = Find-BridgeChrome
$mcpRegistered = (Test-Path -LiteralPath $paths.CodexConfig) -and ((Get-Content -LiteralPath $paths.CodexConfig -Raw -Encoding utf8) -match '(?m)^\[mcp_servers\.web-bridge-codex\]')
$ruleInstalled = (Test-Path -LiteralPath $paths.CodexRules) -and ((Get-Content -LiteralPath $paths.CodexRules -Raw -Encoding utf8) -match 'web-bridge-codex:web-first:start')

@(
    "BRIDGE_DOCTOR",
    "install_root=$($paths.Root)",
    "codex_home=$($paths.CodexHome)",
    "app_present=$(Test-Path -LiteralPath $paths.App)",
    "config_present=$(Test-Path -LiteralPath $paths.ConfigFile)",
    "python_present=$([bool]$python)",
    "venv_present=$(Test-Path -LiteralPath $venvPython)",
    "chrome_present=$([bool]$chrome)",
    "chrome_profile_present=$(Test-Path -LiteralPath $paths.Profile)",
    "codex_mcp_registered=$mcpRegistered",
    "web_first_rule_installed=$ruleInstalled"
    "legacy_install_present=$(Test-Path -LiteralPath $paths.LegacyRoot)"
) -join [Environment]::NewLine

