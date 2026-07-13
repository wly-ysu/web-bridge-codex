[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$doctor = Join-Path $PSScriptRoot "doctor.ps1"
$doctorOutput = & $doctor
if ($LASTEXITCODE -ne 0) { throw "doctor.ps1 failed." }

$required = @(
    "app_present=True",
    "config_present=True",
    "venv_present=True",
    "chrome_profile_present=True",
    "codex_mcp_registered=True",
    "web_first_rule_installed=True"
)
foreach ($item in $required) {
    if ($doctorOutput -notmatch "(?m)^$([regex]::Escape($item))\r?$") {
        throw "Installation verification failed: missing $item"
    }
}

Import-Module (Join-Path $PSScriptRoot "BridgeInstaller.Common.psm1") -Force
$paths = Get-BridgePaths
$mcpConfig = Get-Content -LiteralPath $paths.CodexConfig -Raw -Encoding utf8
$mcpSectionPattern = '(?ms)^\[mcp_servers\.web-bridge-codex\]\r?\n.*?(?=^\[|\z)'
$mcpSections = [regex]::Matches($mcpConfig, $mcpSectionPattern)
if ($mcpSections.Count -ne 1) {
    throw "Installation verification failed: expected exactly one web-bridge-codex MCP section in $($paths.CodexConfig)."
}
if ($mcpSections[0].Value -notmatch '(?m)^enabled\s*=\s*true\s*\r?$') {
    throw "Installation verification failed: web-bridge-codex must be explicitly enabled in $($paths.CodexConfig)."
}
$python = Join-Path $paths.Runtime "Scripts\python.exe"
Push-Location $paths.App
try {
    & $python -c "from server import create_server; create_server(config_path=r'$($paths.ConfigFile)'); print('MCP_SERVER_IMPORT_OK')"
    if ($LASTEXITCODE -ne 0) { throw "The installed MCP server could not load its configuration." }
} finally {
    Pop-Location
}

@(
    "WINDOWS_INSTALL_VERIFY_OK",
    "mcp_server_import=True",
    "mcp_enabled=True",
    "mcp_server=web-bridge-codex",
    "next_action=Sign in to ChatGPT in the dedicated profile, restart Codex, then run ask_web_architect with WINDOWS_INSTALL_SUCCESS."
) -join [Environment]::NewLine
