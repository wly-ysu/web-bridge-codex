Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-BridgePaths {
    $root = Join-Path $env:LOCALAPPDATA "pro_bridge_codex"
    return [ordered]@{
        Root = $root
        App = Join-Path $root "app"
        Config = Join-Path $root "config"
        ConfigFile = Join-Path (Join-Path $root "config") "config.yaml"
        Runtime = Join-Path $root "runtime"
        Logs = Join-Path $root "logs"
        State = Join-Path $root "state"
        Profile = Join-Path $root "chrome-profile"
        Bin = Join-Path $root "bin"
        CodexHome = Join-Path $env:USERPROFILE ".codex"
        CodexConfig = Join-Path (Join-Path $env:USERPROFILE ".codex") "config.toml"
        CodexRules = Join-Path (Join-Path $env:USERPROFILE ".codex") "AGENTS.md"
    }
}

function Ensure-BridgeDirectory([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function Backup-BridgeFile([string]$Path) {
    if (Test-Path -LiteralPath $Path) {
        $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $backup = "$Path.bridge-backup-$stamp"
        Copy-Item -LiteralPath $Path -Destination $backup -Force
        return $backup
    }
    return $null
}

function Get-BridgePython {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return $python.Source }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { return $py.Source }
    return $null
}

function Install-BridgePythonIfNeeded {
    $python = Get-BridgePython
    if ($python) { return $python }
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "Python 3.11+ was not found and winget is unavailable. Install Python, then run this installer again."
    }
    Write-Host "Installing Python with winget..."
    & $winget.Source install --id Python.Python.3.13 -e --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw "winget could not install Python (exit $LASTEXITCODE)." }
    $python = Get-BridgePython
    if (-not $python) {
        throw "Python was installed but is not available in this session. Open a new PowerShell window and run the installer again."
    }
    return $python
}

function Find-BridgeChrome {
    $candidates = @(
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
        "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    if ($candidates.Count -gt 0) { return $candidates[0] }
    return $null
}

function ConvertTo-BridgeTomlString([string]$Value) {
    $normalized = $Value.Replace("\\", "/").Replace('"', '\"')
    return '"' + $normalized + '"'
}

function Set-BridgeMcpRegistration([switch]$Remove) {
    $paths = Get-BridgePaths
    Ensure-BridgeDirectory $paths.CodexHome
    $configPath = $paths.CodexConfig
    $content = if (Test-Path -LiteralPath $configPath) { Get-Content -LiteralPath $configPath -Raw } else { "" }
    $sectionPattern = '(?ms)^\[mcp_servers\.pro_bridge_codex\]\r?\n.*?(?=^\[|\z)'
    if ($content -match $sectionPattern) {
        Backup-BridgeFile $configPath | Out-Null
        $content = [regex]::Replace($content, $sectionPattern, "").TrimEnd()
    }
    if ($Remove) {
        Set-Content -LiteralPath $configPath -Value (($content.TrimEnd()) + [Environment]::NewLine) -Encoding utf8
        return "removed"
    }
    $python = Join-Path $paths.Runtime "Scripts\python.exe"
    $server = Join-Path $paths.App "server.py"
    $entry = @(
        "[mcp_servers.pro_bridge_codex]",
        "command = $(ConvertTo-BridgeTomlString $python)",
        "args = [",
        "  $(ConvertTo-BridgeTomlString $server),",
        "  \"--config\",",
        "  $(ConvertTo-BridgeTomlString $paths.ConfigFile)",
        "]"
    ) -join [Environment]::NewLine
    $newContent = if ([string]::IsNullOrWhiteSpace($content)) { $entry } else { $content.TrimEnd() + [Environment]::NewLine + [Environment]::NewLine + $entry }
    Set-Content -LiteralPath $configPath -Value ($newContent + [Environment]::NewLine) -Encoding utf8
    return "registered"
}

function Set-BridgeWebFirstRule([switch]$Remove) {
    $paths = Get-BridgePaths
    Ensure-BridgeDirectory $paths.CodexHome
    $rulePath = $paths.CodexRules
    $content = if (Test-Path -LiteralPath $rulePath) { Get-Content -LiteralPath $rulePath -Raw } else { "" }
    $pattern = '(?ms)<!-- pro_bridge_codex:web-first:start -->.*?<!-- pro_bridge_codex:web-first:end -->\r?\n?'
    if ($content -match $pattern) {
        Backup-BridgeFile $rulePath | Out-Null
        $content = [regex]::Replace($content, $pattern, "").TrimEnd()
    }
    if (-not $Remove) {
        $managedRule = @'
<!-- pro_bridge_codex:web-first:start -->
# pro_bridge_codex Web-First Rule

For project-related questions, requirements, architecture, implementation, review,
debugging, validation, and project decisions, call `route_to_web_lead` first. If it is
unavailable, call `ask_pro_architect`. Use the returned Web Lead plan before making
project decisions or editing code. Only skip this route when the user starts with
`本地执行：`.
<!-- pro_bridge_codex:web-first:end -->
'@
        $content = if ([string]::IsNullOrWhiteSpace($content)) { $managedRule.TrimEnd() } else { $content.TrimEnd() + [Environment]::NewLine + [Environment]::NewLine + $managedRule.TrimEnd() }
    }
    Set-Content -LiteralPath $rulePath -Value ($content.TrimEnd() + [Environment]::NewLine) -Encoding utf8
}

function Copy-BridgeApplication([string]$SourceDir) {
    $paths = Get-BridgePaths
    if (-not (Test-Path -LiteralPath (Join-Path $SourceDir "server.py"))) {
        throw "SourceDir does not contain server.py: $SourceDir"
    }
    if (Test-Path -LiteralPath $paths.App) { Remove-Item -LiteralPath $paths.App -Recurse -Force }
    Ensure-BridgeDirectory $paths.App
    $excluded = @(".git", "__pycache__", "logs", ".gptpro-browser", "browser_data", "runtime", "dist")
    Get-ChildItem -LiteralPath $SourceDir -Force | Where-Object { $excluded -notcontains $_.Name -and $_.Name -notin @("config.yaml", "bridge_mcp.log", "bridge_launch_matrix.log") } | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $paths.App -Recurse -Force
    }
}

function Write-BridgeConfig([string]$SourceDir) {
    $paths = Get-BridgePaths
    Ensure-BridgeDirectory $paths.Config
    if (Test-Path -LiteralPath $paths.ConfigFile) { return }
    $template = Join-Path $SourceDir "config.example.yaml"
    if (-not (Test-Path -LiteralPath $template)) { throw "Missing configuration template: $template" }
    $content = Get-Content -LiteralPath $template -Raw
    $profilePath = $paths.Profile.Replace("\\", "/")
    $content = [regex]::Replace($content, '(?m)^  user_data_dir:.*$', "  user_data_dir: `"$profilePath`"")
    Set-Content -LiteralPath $paths.ConfigFile -Value $content -Encoding utf8
}

Export-ModuleMember -Function Get-BridgePaths, Ensure-BridgeDirectory, Backup-BridgeFile, Get-BridgePython, Install-BridgePythonIfNeeded, Find-BridgeChrome, Set-BridgeMcpRegistration, Set-BridgeWebFirstRule, Copy-BridgeApplication, Write-BridgeConfig
