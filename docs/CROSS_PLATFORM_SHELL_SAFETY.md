# Cross-platform shell and path safety

This project treats Windows quoting, path conversion, and config serialization as release-blocking risks.

## Core rules

1. Prefer argument arrays over shell strings.
2. Prefer generated temporary scripts over long inline `-Command` strings.
3. Prefer forward slashes in TOML/YAML config paths.
4. Never hand-build TOML, YAML, or JSON with ad-hoc quoting when a structured writer is available.
5. Keep PowerShell, CMD, Bash, and Python command construction isolated in helpers.
6. Test both PowerShell and CMD installer entry points on Windows.
7. Test paths with spaces, Unicode, and backslashes before publishing.
8. Do not rely on a developer machine's existing install as release evidence.

## PowerShell

- Use `-LiteralPath` for filesystem paths supplied by the user or installer.
- Use arrays for `Start-Process -ArgumentList`.
- Use `Join-Path` instead of string concatenation.
- Use `ConvertTo-Json`, TOML helpers, or controlled line builders for config files.
- Avoid embedding multi-line Python, TOML, YAML, or JSON inside one-line `-Command`.
- If inline code is unavoidable, include a nearby comment explaining why it is safe.

## Python

- Use `subprocess.run([...], shell=False)` by default.
- Do not concatenate command strings that contain paths or user-controlled values.
- Use `Path` for local paths and convert at the boundary:
  - Windows process args: `str(path)`
  - YAML/TOML config: `path.as_posix()` when supported by the consumer
- Use `json.dumps` or a TOML/YAML library for escaping, not manual quote replacement.

## Config files

- Config migration must rebuild stale managed config when legacy keys are detected.
- User-owned Codex config must preserve unrelated MCP entries.
- Managed bridge config may be replaced only after creating a backup.
- Forbidden legacy tokens in generated config include:
  - `ask_pro_architect`
  - `review_pro_code`
  - `debug_pro_error`
  - `pro_deep`
  - `pro_budget_policy`
  - `gptpro`
  - fixed model names such as `GPT-5.5`

## CI gate

`tests/release/test_shell_safety.py` is the static guard for these rules.

Allowed exceptions must be explicit and local:

```text
# shell-safety: allow <reason>
```

Use exceptions sparingly. Prefer moving fragile quoting into helpers or test fixtures.

