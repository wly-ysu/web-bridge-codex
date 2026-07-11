# Windows: one-click deployment

This is the only deployment command needed on a new Windows 10/11 machine that already
has Codex installed:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force; irm https://raw.githubusercontent.com/wly-ysu/web-bridge-codex/main/scripts/windows/bootstrap.ps1 | iex
```

If starting from `cmd.exe`, run:

```cmd
curl.exe -fsSL -o "%TEMP%\web-bridge-codex_bootstrap.cmd" https://raw.githubusercontent.com/wly-ysu/web-bridge-codex/main/scripts/windows/bootstrap.cmd && call "%TEMP%\web-bridge-codex_bootstrap.cmd"
```

The installer automatically creates a local, isolated deployment at:

```text
%LOCALAPPDATA%\web-bridge-codex
```

It automatically:

- installs Python with `winget` when missing;
- installs Google Chrome with `winget` when missing;
- installs bridge dependencies into an isolated virtual environment;
- plans an isolated AI Chrome profile, never touching the normal Chrome profile;
- registers the `web-bridge-codex` MCP server in Codex;
- installs the managed Web-First rule so natural-language requests use ChatGPT Web as the
  planner and Codex as the local executor.

Before creating browser data, the installer displays the detected Chrome path and the AI
Profile path, then asks `Create or use this dedicated AI Chrome Profile? [y/N]`. Enter `y`
to approve creation or reuse. Only after approval does it create or reuse the isolated
Profile and open the dedicated AI Chrome login window. The only remaining manual action is
logging into ChatGPT once in that popup window. Then restart Codex and call
`ask_pro_architect` once.

If `winget` is unavailable, the installer stops safely and prints the official Python or
Chrome download link. Install the missing program and run the exact same one-line command
again; installation is idempotent and does not duplicate MCP entries or browser profiles.


