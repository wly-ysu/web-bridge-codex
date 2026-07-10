# Codex-ChatGPTWeb Bridge (MVP)

This project implements a local MCP bridge that makes **Codex the single user entrypoint**
and connects to ChatGPT Web as an architecture/review assistant using the best available
model in your account at runtime.

It provides three MCP tools:

- `route_to_web_lead`
- `ask_pro_architect`
- `review_pro_code`
- `debug_pro_error`

## Windows one-click delivery

Windows 10/11 is the first supported delivery target. The installer creates a
user-level isolated runtime, a dedicated ChatGPT Chrome profile, a Codex MCP
registration, and the global Web-First rule. It never copies the normal Chrome profile.

The global rule defaults every natural-language Codex request to the Web Lead. It keeps
explicit deterministic local execution local and limits automatic Web routing to once per
turn to prevent recursive MCP calls.

From a repository checkout:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\windows\install.ps1
```

From the public GitHub repository:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force; irm https://raw.githubusercontent.com/wly-ysu/web-bridge-codex/main/scripts/windows/bootstrap.ps1 | iex
```

On a bare Windows device that already has Codex, this one command installs Python and
Google Chrome through `winget` when either is missing, then creates the isolated bridge.
The only manual action is ChatGPT login in the dedicated browser window. See
[docs/START_HERE_WINDOWS.md](docs/START_HERE_WINDOWS.md).

For a version-pinned installation, download the Windows ZIP and `SHA256SUMS.txt` from a
GitHub Release, verify the checksum, extract the ZIP, and run
`scripts\windows\install.ps1`.

Sign in to ChatGPT in the dedicated Chrome window, restart Codex, then call
`bridge_health_check`. Full instructions, repair, diagnostics, and uninstall are in
[docs/INSTALL_WINDOWS.md](docs/INSTALL_WINDOWS.md). The platform roadmap is in
[docs/PLATFORM_SUPPORT.md](docs/PLATFORM_SUPPORT.md).

macOS and Linux have preview one-command installers. They require an existing Python 3.11+
installation, Chrome/Chromium, and Codex; they do not use `sudo` or install system packages:

```sh
curl -fsSL https://raw.githubusercontent.com/wly-ysu/web-bridge-codex/main/scripts/unix/bootstrap.sh | sh
```

See [docs/INSTALL_MACOS.md](docs/INSTALL_MACOS.md) and
[docs/INSTALL_LINUX.md](docs/INSTALL_LINUX.md) for platform details.

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

- `ask_pro_architect`

Verified path:

```text
Codex
-> MCP
-> ask_pro_architect
-> ChatGPT Web
-> Codex return
```

Current MVP scope does not include:

- `review_pro_code`
- `debug_pro_error`
- deep profile
- long-context workflows
- CDP daemon

Before using the MVP, confirm Codex has loaded the `pro_bridge_codex` MCP server.
If the MCP server code or tool declarations changed, restart Codex so the server is
reloaded.

Minimal acceptance test:

```text
Call ask_pro_architect:

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

Force Pro only for high-value deep work:

```text
用 Pro 深度分析这个长期架构决策
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

| Scenario | Tool | Profile | Model tendency |
|---|---|---|---|
| Simple judgment | `ask_pro_architect` | `fast` | GPT-5.5 |
| Normal architecture | `ask_pro_architect` | `balanced` | GPT-5.5 |
| 30min-2h complex problem | `ask_pro_architect` | `deep_lite` | GPT-5.5 first |
| 2h+ strategic problem | `ask_pro_architect` | `pro_deep` | GPT-5.5 Pro first |
| Normal review | `review_pro_code` | `review` | GPT-5.5 |
| Critical review | `review_pro_code` | `pro_review` | GPT-5.5 Pro first |
| Normal debug | `debug_pro_error` | `debug` | GPT-5.5 |
| Complex debug | `debug_pro_error` | `pro_debug` | GPT-5.5 Pro first |

## Model Budget Strategy

The default policy is to avoid spending Pro quota.

Normal questions should use GPT-5.5 or the current ChatGPT Web model first. Pro / Pro
extension should be reserved for problems likely to need 2+ hours of deep reasoning or
high-value strategic decisions.

Use GPT-5.5 first for:

- simple explanations
- normal architecture questions
- routine review
- ordinary debug
- medium difficulty questions
- problems likely solvable within 30 minutes

Reserve Pro for:

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
- `profile=pro_deep`

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
- `profile` (string, optional): `fast`, `balanced`, `deep_lite`, or `pro_deep`.
- `execute_after_plan` (bool, default `true`): whether Codex should execute after receiving the plan.

Output:

- Web Lead requirement refinement and Codex execution plan.

### `ask_pro_architect`

Input:

- `question` (string): design question.
- `context_hints` (list[string], optional): files or hints to force include in context.

Output:

- `"<answer>"`

### `review_pro_code`

Input:

- `files` (list[string], optional): file paths to include.
- `diff` (bool, default `true`): include git diff.
- `focus` (string, optional): review goal.

Output:

- `"<answer>"`

### `debug_pro_error`

Input:

- `error_text` (string): compiler/runtime error text.
- `log_path` (string, optional): explicit path for log file.

Output:

- `"<answer>"`

## 5) Notes

- This MVP focuses on safe, targeted context upload (no full-repo dump).
- Sensitive paths are filtered by default (`.git`, `build`, `log`, `data`, `weights`, `*.bag`, `*.pcd`).
- Playwright web mode assumes a login-capable browser profile; first-run may require manual ChatGPT authentication.

## 6) Web Adapter Real-Call Acceptance Checklist

Goal: validate real path `Codex -> MCP -> gptpro_web.py -> Playwright -> Chrome Profile -> ChatGPT Web -> Codex`.

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

Call `ask_pro_architect` with:

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
