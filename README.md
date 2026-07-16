# Codex-ChatGPTWeb Bridge

`web-bridge-codex` makes Codex the local executor and ChatGPT Web the default planner,
architect, reviewer, and debugger. It registers a local MCP server and a managed Web-First
rule: natural-language project requests go to ChatGPT Web first, while explicit deterministic
local work remains local.

## Quick install

You need Codex and an internet connection. The installer uses a dedicated AI browser Profile;
it never copies or modifies your normal Chrome Profile or login data.

## Usage Mode Policy

Daily Codex usage should use the GitHub release installer only. The MCP entry in
`%USERPROFILE%\.codex\config.toml` should point to:

```text
%LOCALAPPDATA%\web-bridge-codex\app\web-bridge-codex.exe
```

The source checkout path, for example `D:\workspcase\pro_bridge_codex\server.py`, is only for
local development and diagnostics. Do not keep normal Codex sessions coupled to the source tree.
After changing MCP tool signatures, packaging, installer behavior, or browser automation, publish
a new release and reinstall from GitHub before treating the change as delivered.

See [docs/USAGE_MODE_POLICY.md](docs/USAGE_MODE_POLICY.md) for the full development and delivery
rules.

| Platform | Status | Dependency behavior | Automated coverage |
|---|---|---|---|
| Windows 10/11 x64 | Primary | Attempts `winget` for missing Python and Chrome | PowerShell and CMD clean-runner smoke tests |
| macOS | Preview | Requires Python 3.11+, Chrome/Chromium, and Codex | Non-GUI install smoke with a fake browser |
| Linux | Preview | Requires Python 3.11+, Chrome/Chromium, and Codex | Ubuntu Docker install smoke with a fake browser |

### Windows PowerShell release install

For an upgrade or repair, completely exit every Codex window first. The active MCP process can
lock the previous compiled runtime. Then run this in **PowerShell**, not CMD:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force; irm https://raw.githubusercontent.com/wly-ysu/web-bridge-codex/main/scripts/release/bootstrap-windows.ps1 | iex
```

The release installer downloads the current Windows native package into `%LOCALAPPDATA%\web-bridge-codex`. The installed `app` directory contains a compiled launcher and runtime only: it does not contain `server.py`, `adapters`, `core`, or `tools`. It displays
the detected browser and dedicated AI Profile path, then asks before creating or reusing that
Profile. If Python or Chrome is missing, it attempts `winget`; success still depends on the
machine's network, policy, and configured package sources.

### Windows CMD release install

Run this in **cmd.exe**, not PowerShell:

```cmd
curl.exe -fsSL -o "%TEMP%\web-bridge-codex_release_bootstrap.cmd" https://raw.githubusercontent.com/wly-ysu/web-bridge-codex/main/scripts/release/bootstrap-windows.cmd && call "%TEMP%\web-bridge-codex_release_bootstrap.cmd"
```

The CMD command enters the same Windows installer. Keep the complete terminal output if it
fails. Both public Windows entrypoints are smoke-tested in isolated GitHub Windows runners.

### macOS (Preview)

macOS currently requires Codex, Python 3.11+ with `venv`, and Google Chrome or Chromium to be
installed first:

```sh
curl -fsSL https://raw.githubusercontent.com/wly-ysu/web-bridge-codex/main/scripts/unix/bootstrap.sh | sh
```

See [docs/INSTALL_MACOS.md](docs/INSTALL_MACOS.md) if a dependency is missing.

### Linux (Preview)

Linux currently requires Codex, Python 3.11+ with `venv`, and Google Chrome or Chromium to be
installed first:

```sh
curl -fsSL https://raw.githubusercontent.com/wly-ysu/web-bridge-codex/main/scripts/unix/bootstrap.sh | sh
```

The automated Linux check uses an Ubuntu Docker container; other distributions, desktop stacks,
enterprise proxies, and browser packaging variants need device-specific validation. See
[docs/INSTALL_LINUX.md](docs/INSTALL_LINUX.md).

### First dedicated browser login

1. Approve creation or reuse of the dedicated AI Profile when prompted.
2. In the browser window opened by the installer, sign in to `https://chatgpt.com` manually.
3. Confirm you can open a new ChatGPT conversation, then close the dedicated browser window.

The installer never reads passwords, cookies, or the normal Chrome Profile. GitHub CI cannot
verify ChatGPT login, MFA/SSO, account entitlement, Web page selectors, or a real model reply.

### Restart Codex and verify

Completely quit and reopen Codex after installation and first login. Existing Codex processes do
not reload newly registered MCP servers or rules automatically.

Then confirm the `web-bridge-codex` MCP server is enabled and call:

```text
bridge_health_check
```

Finally validate the real Web loop with:

```text
ask_web_architect

question:
请只输出 WINDOWS_INSTALL_SUCCESS
```

The expected reply is `WINDOWS_INSTALL_SUCCESS`. A successful local installation does not by
itself prove ChatGPT Web login or browser automation; this final call is the real device check.

### Project conversation continuity

By default, requests from the same local project reuse one ChatGPT Web conversation. This keeps
the Web Lead's plans, constraints, and corrections together instead of creating a new Web chat
for every MCP call. Different projects receive isolated conversations.

The mapping is local to the dedicated bridge profile and is stored under its `state` directory.
It contains only a hash of the project path and a canonical `https://chatgpt.com/c/<id>` URL. It
never stores prompts, responses, cookies, or passwords. After a Codex or Chrome restart, the
next request returns to that same conversation.

Use `conversation_mode: new` only when you explicitly want a fresh Web discussion for the
current project. Use `conversation_mode: one_shot` for a temporary request that must not change
the project's saved conversation. If a saved Web conversation was explicitly deleted or is no
longer accessible, the bridge creates one replacement conversation once; temporary network or
generation failures do not create new chats.

### Browser worker lifecycle

The ChatGPT Web browser is owned by one user-scoped Browser Broker, not by an individual MCP
process. Every Codex project connects to that singleton through an authenticated loopback socket.
Requests from different projects may arrive concurrently, but one global queue serializes the
Playwright operations so a single dedicated Chrome Profile is never launched by two processes.

Each request opens a fresh ChatGPT tab, waits for the answer, then closes only that request tab.
Project conversation mappings and browser ownership stay in the broker process, so later requests
reuse the correct Web conversation without cold-starting Chrome or racing another Codex task.

A single `about:blank` tab may remain open as a keepalive tab. This is intentional: closing the
last tab can close the Chrome window and release the persistent profile. The bridge does not
depend on the foreground tab when closing a request tab; Playwright closes the exact page object
created for that request.

For stability, one Chrome profile is operated serially. If two projects ask Web Lead at the same
time, the second request waits until the first request finishes. This avoids shared-profile races,
mixed streaming responses, and `profile_in_use` failures while still preserving per-project
ChatGPT conversation URLs.

Use `bridge_browser_status` to inspect the live worker and `bridge_browser_shutdown` to manually
close the persistent browser when upgrading or troubleshooting.

### Required Codex integration layers

The delivery has two required, separate layers. Both must be present after a Windows install:

| Layer | Target path | Responsibility |
|---|---|---|
| MCP registration | `%USERPROFILE%\.codex\config.toml` | Lets Codex discover, start, and call the `web-bridge-codex` STDIO server. |
| Global Web-First rule | `%USERPROFILE%\.codex\AGENTS.md` | Requires natural-language project requests to call Web Lead before Codex plans or implements work. |

The installer creates a managed `web-bridge-codex` block in the user-level `AGENTS.md` without
replacing unrelated instructions. The only local bypass is an explicit `本地执行：` prefix for a
deterministic local command. This keeps Codex as the executor and ChatGPT Web as the planner for
all normal project conversations.

`MCP enabled` in the Codex UI proves only the first layer. It does not prove automatic routing.
See [global routing and troubleshooting](docs/CODEX_GLOBAL_ROUTING.md) for the redacted config
shape, target paths, and a cross-device verification procedure.

### CI and detailed docs

GitHub Actions checks PowerShell and CMD Windows bootstrap installs, PowerShell syntax, Linux
shell syntax, an Ubuntu Docker install smoke, and a macOS non-GUI install smoke. It does not
perform real ChatGPT login or conversation tests.

- [Windows quick start](docs/START_HERE_WINDOWS.md)
- [Windows installation, repair, and uninstall](docs/INSTALL_WINDOWS.md)
- [global Web-First routing and troubleshooting](docs/CODEX_GLOBAL_ROUTING.md)
- [macOS installation](docs/INSTALL_MACOS.md)
- [Linux installation](docs/INSTALL_LINUX.md)
- [platform support and limits](docs/PLATFORM_SUPPORT.md)

The bridge collects local repository context (git status/diff/files/logs),
builds compact prompts and sends them to ChatGPT Web through one of:

- `Web` adapter (Playwright, default), or
- `API` adapter (OpenAI API).

## 1) Setup

```bash
python -m pip install -r requirements.txt
```

Edit `config.yaml` to tune context limits, adapter settings, and ignore rules.
For a fresh checkout, copy `config.example.yaml` to `config.yaml` first, then set
your local Chrome profile path if needed.

## 2) Run MCP server

```bash
python server.py
```

Then configure Codex to load this MCP server in your environment.

## MVP Delivery Status

The current delivered MVP supports the real ChatGPT Web bridge for:

- `ask_web_architect`

Verified path:

```text
Codex
-> MCP
-> ask_web_architect
-> ChatGPT Web
-> Codex return
```

Current MVP scope does not include:

- `review_web_code`
- `debug_web_error`
- deep profile
- long-context workflows
- CDP daemon

Before using the MVP, confirm Codex has loaded the `web-bridge-codex` MCP server.
If the MCP server code or tool declarations changed, restart Codex so the server is
reloaded.

Minimal acceptance test:

```text
Call ask_web_architect:

profile: fast
include_workspace_context: false
question:
请只输出：

MVP_WEB_BRIDGE_SUCCESS

要求：
不要解释，不要分析，不要输出其他内容。
```

Expected Codex result:

```text
MVP_WEB_BRIDGE_SUCCESS
```

For the current delivery scope, pending validation work, and roadmap priorities, see
[docs/REQUIREMENTS_ROADMAP.md](docs/REQUIREMENTS_ROADMAP.md).

## Web-First Usage

Daily usage should follow the Web-First workflow:

```text
User vague request
-> route_to_web_lead
-> Web Lead refines requirement and returns a plan
-> Codex executes the plan
```

Normal user input:

```text
实现未完成需求
```

Architecture input:

```text
这个模块架构怎么看？
```

Correction during execution:

```text
不对，先修 tab 泄漏，不要改模型策略
```

Codex should route these natural-language requests to Web Lead first.

If you only want local execution and do not want Web Lead planning, use:

```text
本地执行：查看 git diff
```

Use the strongest Web mode only for high-value deep work:

```text
用最强 Web 模型深度分析这个长期架构决策
```

For the full workflow rules, see [docs/WEB_FIRST_WORKFLOW.md](docs/WEB_FIRST_WORKFLOW.md).

For the future multi-provider design covering Doubao, DeepSeek, Xiaomi, and other
free Web AI providers, see
[docs/MULTI_WEB_AI_ARCHITECTURE.md](docs/MULTI_WEB_AI_ARCHITECTURE.md).

## Web Tech Lead Workflow

Codex is the executor. ChatGPT Web is the Tech Lead.

Codex should handle local execution work: reading files, editing code, running commands,
building, testing, and applying patches. Non-execution reasoning should normally go to
ChatGPT Web first: architecture analysis, design decisions, risk judgment, review,
debug strategy, multi-option tradeoffs, patent or algorithm analysis, and other complex
technical thinking.

Default flow:

```text
User asks natural language question
-> Codex classifies task
-> non-execution reasoning goes to ChatGPT Web MCP
-> ChatGPT Web returns plan
-> Codex executes plan
```

Model selection policy:

| Scenario | Tool | Profile | Runtime model behavior |
|---|---|---|---|
| Simple judgment | `ask_web_architect` | `fast` | Current available Web model, concise response |
| Normal architecture | `ask_web_architect` | `balanced` | Best available Web capability, balanced reasoning |
| 30min-2h complex problem | `ask_web_architect` | `deep_lite` | Best available Web capability, deeper reasoning |
| 2h+ strategic problem | `ask_web_architect` | `deep` | Strongest available Web capability, then automatic downgrade |
| Normal review | `review_web_code` | `review` | Best available Web capability, balanced reasoning |
| Critical review | `review_web_code` | `critical_review` | Strongest available Web capability, then automatic downgrade |
| Normal debug | `debug_web_error` | `debug` | Best available Web capability, balanced reasoning |
| Complex debug | `debug_web_error` | `deep_debug` | Strongest available Web capability, then automatic downgrade |

## Model Budget Strategy

ChatGPT Web is the source of truth for currently available models. The bridge first attempts
the strongest visible capability tier; if its quota is exhausted or unavailable, it tries the
next tier and finally continues with the current Web selection. Profile names describe task
complexity and latency preference, not a fixed model version.

Use lower-complexity profiles for:

- simple explanations
- normal architecture questions
- routine review
- ordinary debug
- medium difficulty questions
- problems likely solvable within 30 minutes

Use high-complexity profiles for:

- 2h+ deep architecture reasoning
- patent / innovation strategy
- autonomous driving safety-critical architecture
- unresolved multi-round failures
- complex cross-module migration strategy
- high-risk final architecture review
- long-term project direction decisions

Users can explicitly request:

- `profile=fast`
- `profile=balanced`
- `profile=deep_lite`
- `profile=deep`

## Web response waiting policy

The bridge uses a progress-aware response wait state machine so a long ChatGPT Web answer
is not treated as a timeout while its text continues to grow. Defaults are: first response
within 60 seconds, no text progress for 30 seconds before a stall is declared, 600 seconds
maximum response time, and a one-second poll interval. Configure these values under
`web_adapter.response_wait` in `config.yaml`.

## 3) Environment variables

- `GPTPRO_ADAPTER` : `web` (default) or `api`
- `OPENAI_API_KEY` : required for API mode
- `OPENAI_API_BASE` : optional OpenAI API endpoint
- `OPENAI_ORG_ID` : optional
- `GPTPRO_WEBDRIVER` : optional, if you want to run a specific Chromium executable

## 4) Tool interfaces

### `route_to_web_lead`

Input:

- `message` (string): natural-language user request or correction.
- `mode` (string, optional): workflow mode, default `web_first`.
- `profile` (string, optional): `fast`, `balanced`, `deep_lite`, or `deep`.
- `execute_after_plan` (bool, default `true`): whether Codex should execute after receiving the plan.
- `conversation_mode` (optional): `reuse_or_create` (default), `new`, or `one_shot`.

Output:

- Web Lead requirement refinement and Codex execution plan.

### `ask_web_architect`

Input:

- `question` (string): design question.
- `context_hints` (list[string], optional): files or hints to force include in context.
- `include_workspace_context` (bool, default `false`): explicitly include repository context.
- `profile` (string, optional): `fast`, `balanced`, `deep_lite`, or `deep`.
- `conversation_mode` (optional): `reuse_or_create` (default), `new`, or `one_shot`.

Output:

- `"<answer>"`

### Repository-link context (default)

Web Lead receives the GitHub repository URL, branch, and committed GitHub URL when
available. It does not receive local source text, Git diff text, logs, or local
machine paths. `review_web_code` requires a clean working tree so it can review
the exact linked commit; commit or open a PR before requesting Web review.

Set `context.transport: workspace_text` and explicitly opt in only if a legacy
local-text workflow is required.

### `review_web_code`

Input:

- `files` (list[string], optional): file paths to include.
- `diff` (bool, default `true`): include git diff.
- `focus` (string, optional): review goal.

Output:

- `"<answer>"`

### `debug_web_error`

Input:

- `error_text` (string): compiler/runtime error text.
- `log_path` (string, optional): explicit path for log file.

Output:

- `"<answer>"`

## 5) Notes

- This MVP focuses on safe, targeted context upload (no full-repo dump).
- Sensitive paths are filtered by default (`.git`, `build`, `log`, `data`, `weights`, `*.bag`, `*.pcd`).
- Playwright web mode assumes a login-capable browser profile; first-run may require manual ChatGPT authentication.

## Feedback and issues

If you run into a problem, please open a GitHub Issue:

- https://github.com/wly-ysu/web-bridge-codex/issues

We review reported issues and will do our best to help or fix confirmed problems based on impact and maintenance priority.

## 6) Web Adapter Real-Call Acceptance Checklist

Goal: validate real path `Codex -> MCP -> chatgpt_web.py -> Playwright -> Chrome Profile -> ChatGPT Web -> Codex`.

### Step 1: confirm real browser profile path

- Open `config.yaml` and set:
  - `web_adapter.user_data_dir` to your real user profile directory, or
  - leave empty to auto-detect typical:
    - `C:\Users\<user>\AppData\Local\Google\Chrome\User Data`
    - `C:\Users\<user>\AppData\Local\Microsoft\Edge\User Data`

### Step 2: show browser UI

- In `config.yaml` set:
  - `web_adapter.headless: false`
  - `web_adapter.channel: "chrome"` (or `"msedge"` if needed)

### Step 3: non-technical probe question

Call `ask_web_architect` with:

```
请完成以下任务：

1. 输出当前北京时间
2. 输出一个随机六位数字
3. 最后一行必须写：
GPT_PRO_WEB_REAL_TEST
```

You should visually see:

- Chrome opens
- `https://chatgpt.com` page opens
- input field receives prompt
- chat answer contains:
  - current date/time
  - random 6-digit number
  - last line `GPT_PRO_WEB_REAL_TEST`

### Step 4: read logs

Search logs for:

- `[WEB] query start`
- `[WEB] launch persistent context`
- `[WEB] goto start`
- `[WEB] page loaded`
- `[WEB] input selector found`
- `[WEB] typing prompt`
- `[WEB] send clicked`
- `[WEB] waiting assistant response`
- `[WEB] response length`
- `[WEB] close context`

If you see `input selector not found`, adjust selectors in:

- `web_adapter.input_selectors`
- `web_adapter.send_selectors`
- `web_adapter.response_selectors`

Recommended values are already included:

- `#prompt-textarea`
- `div[contenteditable='true']`
- `[data-message-author-role='assistant']`
