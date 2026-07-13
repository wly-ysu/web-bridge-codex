# Usage Mode Policy

`web-bridge-codex` has two valid modes. Keep them separate.

## Daily Use

Daily Codex usage must run the GitHub release installation.

The active MCP registration should point to:

```text
%LOCALAPPDATA%\web-bridge-codex\app\web-bridge-codex.exe
```

and use:

```text
%LOCALAPPDATA%\web-bridge-codex\config\config.yaml
```

This is the only mode that should be considered user-facing or delivered.

Use this mode for:

- normal project questions
- Web-First planning
- real ChatGPT Web calls
- cross-device validation
- user documentation
- release acceptance tests

## Development Use

The source checkout is only for development and diagnostics.

Example source path:

```text
D:\workspcase\pro_bridge_codex\server.py
```

Use this mode only for:

- editing code
- running unit tests
- checking MCP schemas before packaging
- debugging a local implementation issue

Do not leave normal Codex usage configured to the source tree. Source mode can hide packaging,
installer, release, and stale-schema problems.

## Delivery Rule

A fix is not delivered when it only passes from the source tree.

A fix is delivered only after:

1. Source tests pass.
2. MCP schema checks pass.
3. The fix is committed and pushed.
4. GitHub CI passes.
5. A new GitHub release is built.
6. The local machine installs from the GitHub release command.
7. Codex is restarted.
8. The installed MCP returns the expected result from a real Codex task.

## Local Verification

First confirm the active MCP registration:

```text
%USERPROFILE%\.codex\config.toml
```

Expected release registration:

```toml
[mcp_servers.web-bridge-codex]
command = "C:/Users/<user>/AppData/Local/web-bridge-codex/app/web-bridge-codex.exe"
args = ["--config", "C:/Users/<user>/AppData/Local/web-bridge-codex/config/config.yaml"]
```

Then restart Codex and run:

```text
bridge_health_check
```

Finally run the real Web loop:

```text
ask_pro_architect:
profile: fast
include_workspace_context: false
question:
请只输出：
MVP_WEB_BRIDGE_SUCCESS
```

Expected result:

```text
MVP_WEB_BRIDGE_SUCCESS
```

If a source edit changes a tool signature, the installed release must be rebuilt and reinstalled
before this test is meaningful.
