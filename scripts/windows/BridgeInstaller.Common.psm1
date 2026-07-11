Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-BridgePaths {
    $root = Join-Path $env:LOCALAPPDATA "web-bridge-codex"
    $codexHome = if ([string]::IsNullOrWhiteSpace($env:CODEX_HOME)) {
        Join-Path $env:USERPROFILE ".codex"
    } else {
        $env:CODEX_HOME
    }
    return [ordered]@{
        Root = $root
        LegacyRoot = Join-Path $env:LOCALAPPDATA "pro_bridge_codex"
        App = Join-Path $root "app"
        Config = Join-Path $root "config"
        ConfigFile = Join-Path (Join-Path $root "config") "config.yaml"
        Runtime = Join-Path $root "runtime"
        Logs = Join-Path $root "logs"
        State = Join-Path $root "state"
        Profile = Join-Path $root "chrome-profile"
        Bin = Join-Path $root "bin"
        CodexHome = $codexHome
        CodexConfig = Join-Path $codexHome "config.toml"
        CodexRules = Join-Path $codexHome "AGENTS.md"
    }
}

function Migrate-LegacyBridgeInstall {
    $paths = Get-BridgePaths
    if (-not (Test-Path -LiteralPath $paths.LegacyRoot)) { return "not_found" }
    if (Test-Path -LiteralPath $paths.Root) {
        throw "Both legacy ($($paths.LegacyRoot)) and current ($($paths.Root)) bridge directories exist. Installation stopped to avoid data loss; keep the current directory and remove or back up the legacy directory before retrying."
    }
    Move-Item -LiteralPath $paths.LegacyRoot -Destination $paths.Root -ErrorAction Stop
    if (Test-Path -LiteralPath $paths.ConfigFile) {
        $legacyForward = $paths.LegacyRoot.Replace("\", "/")
        $currentForward = $paths.Root.Replace("\", "/")
        $content = Get-Content -LiteralPath $paths.ConfigFile -Raw -Encoding utf8
        $content = $content.Replace($paths.LegacyRoot, $paths.Root).Replace($legacyForward, $currentForward)
        Set-Content -LiteralPath $paths.ConfigFile -Value $content -Encoding utf8
    }
    return "migrated"
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

function Get-BridgeServerProcesses {
    $paths = Get-BridgePaths
    $serverPath = Join-Path $paths.App "server.py"
    $matching = @()
    try {
        $matching = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
            $_.CommandLine -and $_.CommandLine.IndexOf($serverPath, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
        })
    } catch {
        return @()
    }
    return $matching
}

function Get-BridgePython {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return $python.Source }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { return $py.Source }
    $roots = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python"),
        (Join-Path $env:ProgramFiles "Python"),
        (Join-Path ${env:ProgramFiles(x86)} "Python")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    foreach ($root in $roots) {
        $candidate = Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            ForEach-Object {
                $exe = Join-Path $_.FullName "python.exe"
                if (Test-Path -LiteralPath $exe) { $exe }
            } |
            Select-Object -First 1
        if ($candidate) { return $candidate }
    }
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
    $candidateList = @($candidates)
    if ($candidateList.Count -gt 0) { return $candidateList[0] }
    return $null
}

function Install-BridgeChromeIfNeeded {
    $chrome = Find-BridgeChrome
    if ($chrome) { return $chrome }
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "Google Chrome is required. Download and install it from https://www.google.com/chrome/ , then run the same one-click installer again."
    }
    Write-Host "Google Chrome was not found. Installing it with winget..."
    & $winget.Source install --id Google.Chrome -e --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "winget could not install Google Chrome (exit $LASTEXITCODE). Install it from https://www.google.com/chrome/ , then run the same installer again."
    }
    $chrome = Find-BridgeChrome
    if (-not $chrome) {
        throw "Google Chrome was installed but could not be located. Restart Windows or install it from https://www.google.com/chrome/ , then re-run the installer."
    }
    return $chrome
}

function ConvertTo-BridgeTomlString([string]$Value) {
    $normalized = $Value.Replace("\", "/").Replace('"', '\"')
    return '"' + $normalized + '"'
}

function Set-BridgeMcpRegistration([switch]$Remove) {
    $paths = Get-BridgePaths
    Ensure-BridgeDirectory $paths.CodexHome
    $configPath = $paths.CodexConfig
    $content = if (Test-Path -LiteralPath $configPath) { Get-Content -LiteralPath $configPath -Raw -Encoding utf8 } else { "" }
    $originalContent = $content
    # Match the bridge parent table and every descendant table. Removing only the parent leaves
    # legacy entries such as [mcp_servers.pro_bridge_codex.tools.<name>] behind on upgrade.
    $sectionPattern = '(?ms)^\[mcp_servers\.(?:pro_bridge_codex|web-bridge-codex)(?:\.[^\]]+)?\]\r?\n.*?(?=^\[|\z)'
    $content = [regex]::Replace($content, $sectionPattern, "").TrimEnd()
    if ($Remove) {
        $newContent = if ([string]::IsNullOrWhiteSpace($content)) { "" } else { $content.TrimEnd() + [Environment]::NewLine }
        if ($newContent -eq $originalContent) { return "unchanged" }
        if (Test-Path -LiteralPath $configPath) { Backup-BridgeFile $configPath | Out-Null }
        Set-Content -LiteralPath $configPath -Value $newContent -Encoding utf8
        return "removed"
    }
    $python = Join-Path $paths.Runtime "Scripts\python.exe"
    $server = Join-Path $paths.App "server.py"
    $logPath = Join-Path $paths.Logs "bridge_mcp.log"
    $entry = @(
        "[mcp_servers.web-bridge-codex]",
        "enabled = true",
        "command = $(ConvertTo-BridgeTomlString $python)",
        "env = { WEB_BRIDGE_LOG_PATH = $(ConvertTo-BridgeTomlString $logPath) }",
        "args = [",
        "  $(ConvertTo-BridgeTomlString $server),",
        '  "--config",',
        "  $(ConvertTo-BridgeTomlString $paths.ConfigFile)",
        "]"
    ) -join [Environment]::NewLine
    $newContent = if ([string]::IsNullOrWhiteSpace($content)) { $entry } else { $content.TrimEnd() + [Environment]::NewLine + [Environment]::NewLine + $entry }
    $newContent += [Environment]::NewLine
    if ($newContent -eq $originalContent) { return "unchanged" }
    if (Test-Path -LiteralPath $configPath) { Backup-BridgeFile $configPath | Out-Null }
    Set-Content -LiteralPath $configPath -Value $newContent -Encoding utf8
    return "registered"
}

function Set-BridgeWebFirstRule([switch]$Remove) {
    $paths = Get-BridgePaths
    Ensure-BridgeDirectory $paths.CodexHome
    $rulePath = $paths.CodexRules
    $content = if (Test-Path -LiteralPath $rulePath) { Get-Content -LiteralPath $rulePath -Raw -Encoding utf8 } else { "" }
    $originalContent = $content
    $startPattern = '<!-- (?:pro_bridge_codex|web-bridge-codex):web-first:start -->'
    $endPattern = '<!-- (?:pro_bridge_codex|web-bridge-codex):web-first:end -->'
    $starts = [regex]::Matches($content, $startPattern).Count
    $ends = [regex]::Matches($content, $endPattern).Count
    if ($starts -ne $ends -or $starts -gt 1) {
        throw "Managed Web-First rule conflict in $rulePath. Expected zero or one complete bridge rule block; no changes were made."
    }
    $patterns = @(
        '(?ms)<!-- pro_bridge_codex:web-first:start -->.*?<!-- pro_bridge_codex:web-first:end -->\r?\n?',
        '(?ms)<!-- web-bridge-codex:web-first:start -->.*?<!-- web-bridge-codex:web-first:end -->\r?\n?'
    )
    foreach ($pattern in $patterns) {
        $content = [regex]::Replace($content, $pattern, "").TrimEnd()
    }
    if (-not $Remove) {
        $managedRule = @'
<!-- web-bridge-codex:web-first:start -->
# web-bridge-codex Web-First Rule

Default all natural-language requests to `route_to_web_lead` first. If it is unavailable,
use `ask_pro_architect`. Use the returned Web Lead plan before making decisions or editing
code. Do not route an explicit deterministic local operation, a request beginning with
`本地执行：`, or any content that came from Web MCP / is already Web-reviewed. Limit automatic
Web routing to once per user turn. If Web MCP times out, is unavailable, or authentication
fails, retry once at most, then continue locally with stated assumptions; never block or
recurse indefinitely.
<!-- web-bridge-codex:web-first:end -->
'@
        $content = if ([string]::IsNullOrWhiteSpace($content)) { $managedRule.TrimEnd() } else { $content.TrimEnd() + [Environment]::NewLine + [Environment]::NewLine + $managedRule.TrimEnd() }
    }
    $newContent = if ([string]::IsNullOrWhiteSpace($content)) { "" } else { $content.TrimEnd() + [Environment]::NewLine }
    if ($newContent -eq $originalContent) { return "unchanged" }
    if (Test-Path -LiteralPath $rulePath) { Backup-BridgeFile $rulePath | Out-Null }
    Set-Content -LiteralPath $rulePath -Value $newContent -Encoding utf8
    if ($Remove) { return "removed" }
    return "registered"
}

function Copy-BridgeApplication([string]$SourceDir) {
    $paths = Get-BridgePaths
    if (-not (Test-Path -LiteralPath (Join-Path $SourceDir "server.py"))) {
        throw "SourceDir does not contain server.py: $SourceDir"
    }
    if (Test-Path -LiteralPath $paths.App) {
        $activeServers = @(Get-BridgeServerProcesses)
        if ($activeServers.Count -gt 0) {
            throw "An active web-bridge-codex MCP server is using the installed application. Completely close Codex, then rerun the installer."
        }
        Remove-Item -LiteralPath $paths.App -Recurse -Force
    }
    Ensure-BridgeDirectory $paths.App
    $excluded = @(".git", "__pycache__", "logs", ".gptpro-browser", "browser_data", "runtime", "dist")
    Get-ChildItem -LiteralPath $SourceDir -Force | Where-Object { $excluded -notcontains $_.Name -and $_.Name -notin @("config.yaml", "bridge_mcp.log", "bridge_launch_matrix.log") } | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $paths.App -Recurse -Force
    }
}

function Write-BridgeConfig([string]$SourceDir, [string]$ChromePath = "") {
    $paths = Get-BridgePaths
    Ensure-BridgeDirectory $paths.Config
    $chromePathForYaml = $ChromePath.Replace("\", "/")
    if (Test-Path -LiteralPath $paths.ConfigFile) {
        if (-not [string]::IsNullOrWhiteSpace($chromePathForYaml)) {
            $content = Get-Content -LiteralPath $paths.ConfigFile -Raw -Encoding utf8
            if ($content -match '(?m)^  executable_path:') {
                $updated = [regex]::Replace(
                    $content,
                    '(?m)^  executable_path:\s*""\s*$',
                    "  executable_path: `"$chromePathForYaml`""
                )
            } else {
                $updated = [regex]::Replace(
                    $content,
                    '(?m)^(  user_data_dir:.*)$',
                    "`$1$([Environment]::NewLine)  executable_path: `"$chromePathForYaml`""
                )
            }
            if ($updated -ne $content) {
                Backup-BridgeFile $paths.ConfigFile | Out-Null
                Set-Content -LiteralPath $paths.ConfigFile -Value $updated -Encoding utf8
            }
        }
        return
    }
    $template = Join-Path $SourceDir "config.example.yaml"
    if (-not (Test-Path -LiteralPath $template)) { throw "Missing configuration template: $template" }
    $content = Get-Content -LiteralPath $template -Raw -Encoding utf8
    $profilePath = $paths.Profile.Replace("\", "/")
    $content = [regex]::Replace($content, '(?m)^  user_data_dir:.*$', "  user_data_dir: `"$profilePath`"")
    if (-not [string]::IsNullOrWhiteSpace($chromePathForYaml)) {
        $content = [regex]::Replace($content, '(?m)^  executable_path:.*$', "  executable_path: `"$chromePathForYaml`"")
    }
    Set-Content -LiteralPath $paths.ConfigFile -Value $content -Encoding utf8
}

Export-ModuleMember -Function Get-BridgePaths, Migrate-LegacyBridgeInstall, Ensure-BridgeDirectory, Backup-BridgeFile, Get-BridgeServerProcesses, Get-BridgePython, Install-BridgePythonIfNeeded, Find-BridgeChrome, Install-BridgeChromeIfNeeded, Set-BridgeMcpRegistration, Set-BridgeWebFirstRule, Copy-BridgeApplication, Write-BridgeConfig

