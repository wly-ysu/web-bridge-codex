[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "BridgeInstaller.Common.psm1") -Force
$paths = Get-BridgePaths
$python = Get-BridgePython
$venvPython = Join-Path $paths.Runtime "Scripts\python.exe"
$chrome = Find-BridgeChrome
$mcpRegistered = (Test-Path -LiteralPath $paths.CodexConfig) -and ((Get-Content -LiteralPath $paths.CodexConfig -Raw) -match '(?m)^\[mcp_servers\.pro_bridge_codex\]')
$ruleInstalled = (Test-Path -LiteralPath $paths.CodexRules) -and ((Get-Content -LiteralPath $paths.CodexRules -Raw) -match 'pro_bridge_codex:web-first:start')

@(
    "BRIDGE_DOCTOR",
    "install_root=$($paths.Root)",
    "app_present=$(Test-Path -LiteralPath $paths.App)",
    "config_present=$(Test-Path -LiteralPath $paths.ConfigFile)",
    "python_present=$([bool]$python)",
    "venv_present=$(Test-Path -LiteralPath $venvPython)",
    "chrome_present=$([bool]$chrome)",
    "chrome_profile_present=$(Test-Path -LiteralPath $paths.Profile)",
    "codex_mcp_registered=$mcpRegistered",
    "web_first_rule_installed=$ruleInstalled"
) -join [Environment]::NewLine
