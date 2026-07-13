---
name: windows-shell-safety
description: Use when editing or reviewing Windows, PowerShell, CMD, Bash, GitHub Actions, installer scripts, Codex MCP config, TOML/YAML/JSON generation, path conversion, or command invocation logic. Helps prevent quoting, escaping, Unicode path, backslash, WSL/Git Bash/CMD/PowerShell, and config serialization bugs.
---

# Windows shell safety

Before changing installer, release, CI, MCP registration, or command-running code, apply these rules.

## Required workflow

1. Identify every shell boundary: PowerShell, CMD, Bash, Python subprocess, GitHub Actions, TOML, YAML, JSON.
2. Keep paths as structured values until the boundary.
3. Use helper functions for quoting and config generation.
4. Add or update tests for PowerShell and CMD paths.
5. Run the project shell safety test before claiming the change is releasable.

## Hard rules

- Prefer `subprocess.run([...], shell=False)` in Python.
- Prefer `Start-Process -ArgumentList @(...)` or direct invocation with separate arguments in PowerShell.
- Prefer `Join-Path` and `-LiteralPath` for filesystem paths.
- Prefer forward slashes inside config paths consumed by Codex or Python.
- Do not hand-build long inline `powershell -Command` or `python -c` strings when a script file or helper can be used.
- Do not hand-build TOML/YAML/JSON by concatenating unescaped user paths.
- Do not use user-controlled paths in regex replacement strings without escaping.
- Keep unrelated user Codex config, AGENTS.md content, Chrome profile, and other MCP entries intact.

## Test matrix

Cover these cases when installer behavior changes:

- PowerShell 5.1 entry point.
- PowerShell 7 entry point when available.
- CMD entry point.
- Path with spaces.
- Path with non-ASCII characters.
- Existing old bridge config containing legacy names.
- Existing unrelated MCP registrations.
- Existing malformed managed rule markers.

## Exception rule

If fragile inline shell is unavoidable, place this exact comment next to it:

```text
shell-safety: allow <short reason>
```

The reason must explain why a helper or script file is not suitable.

