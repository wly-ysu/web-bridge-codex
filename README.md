# Codex-ChatGPTWeb Bridge (MVP)

This project implements a local MCP bridge that makes **Codex the single user entrypoint**
and connects to ChatGPT Web as an architecture/review assistant using the best available
model in your account at runtime.

It provides three MCP tools:

- `ask_pro_architect`
- `review_pro_code`
- `debug_pro_error`

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

## 3) Environment variables

- `GPTPRO_ADAPTER` : `web` (default) or `api`
- `OPENAI_API_KEY` : required for API mode
- `OPENAI_API_BASE` : optional OpenAI API endpoint
- `OPENAI_ORG_ID` : optional
- `GPTPRO_WEBDRIVER` : optional, if you want to run a specific Chromium executable

## 4) Tool interfaces

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
