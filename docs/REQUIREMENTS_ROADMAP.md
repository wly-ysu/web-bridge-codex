# pro_bridge_codex Requirements Roadmap

## Current Summary

The MVP has delivered the minimum real ChatGPT Web bridge:

```text
Codex
-> MCP
-> ask_pro_architect
-> ChatGPT Web
-> Codex return
```

Verified success marker:

```text
MVP_WEB_BRIDGE_SUCCESS
```

This confirmed path is not a mock, not an API fallback, and not a local fake return.

The next goal is to turn the MVP into a daily-use tool:

- no Chrome tab leakage
- `review_pro_code` and `debug_pro_error` validated end to end
- natural language routing verified
- GPT-5.5 / Pro budget used deliberately
- workspace context restored and verified

For the long-term multi-provider architecture covering Doubao, DeepSeek, Xiaomi,
and other free Web AI providers, see
[MULTI_WEB_AI_ARCHITECTURE.md](MULTI_WEB_AI_ARCHITECTURE.md).

## Delivered And Verified

### 1. Minimal Codex to ChatGPT Web Loop

Status: delivered and verified.

Verified path:

```text
Codex
-> MCP
-> ask_pro_architect
-> ChatGPT Web
-> Codex return
```

Verified marker:

```text
MVP_WEB_BRIDGE_SUCCESS
```

### 2. MCP Registration And Tool Discovery

Status: delivered.

Current MCP tools:

- `ask_pro_architect`
- `review_pro_code`
- `debug_pro_error`
- `bridge_health_check`
- `bridge_chrome_preflight`
- `bridge_chrome_smoke_test`
- `bridge_chrome_lifecycle_test`

### 3. ChatGPT Web Adapter MVP Capabilities

Status: delivered for `ask_pro_architect`.

Implemented capabilities:

- dedicated Chrome profile support
- Playwright Chrome launch
- ChatGPT Web navigation
- fresh page creation
- prompt send
- assistant response capture
- marker early return
- `fast` profile minimal call

### 4. Chrome Diagnostics

Status: delivered.

Available diagnostics:

- `bridge_health_check`
- `bridge_chrome_preflight`
- `bridge_chrome_smoke_test`
- `bridge_chrome_lifecycle_test`
- `scripts/chrome_launch_matrix.py`

These helped diagnose:

- profile lock
- stale lock
- old page reuse
- persistent context lifecycle
- close warning masking
- `page.goto` failures
- response wait selector failures

### 5. Model Naming Strategy

Status: direction delivered.

The bridge is no longer positioned as requiring GPT-5.5 Pro. The intended behavior is:

```text
Use the current available ChatGPT Web model.
```

Policy:

- use Pro when available and appropriate
- fall back to GPT-5.5 / current web model
- do not fail just because Pro is unavailable

## Pending Core Validation

### P0: Chrome Tab Leak Fix And Validation

Current concern:

AI Chrome accumulates many tabs over repeated calls.

Risk:

- Chrome memory growth
- increasing `context.pages`
- selector confusion
- ChatGPT page slowdown
- eventual bridge instability

Required behavior:

- close only the fresh page created by the current call
- do not close historical or user-created pages
- `page.close` / `context.close` warnings must not override successful answers
- multiple `ask_pro_architect` calls should not grow tab count

Desired validation:

```text
fresh_page_closed=true
```

Priority: P0.

### P0: Validate review_pro_code

Current status:

Defined but not fully verified end to end.

Required validation:

```text
review 当前 git diff
```

Must confirm:

- git diff collection
- prompt delivery to ChatGPT Web
- review response returns to Codex
- response wait works
- no tab leak occurs

Priority: P0.

### P0: Validate debug_pro_error

Current status:

Defined but not fully verified end to end.

Required validation example:

```text
Target page, context or browser has been closed
```

Must confirm:

- error text is sent to ChatGPT Web
- debugging analysis returns to Codex
- response wait works
- no tab leak occurs

Priority: P0.

### P1: Natural Language Routing Validation

Goal:

The user should be able to type:

```text
这个模块架构怎么看？
```

Expected routing:

```text
ask_pro_architect
profile=balanced
```

Current status:

Rules exist in `AGENTS.md` and routing docs, but runtime behavior still needs validation.

Priority: P1.

### P1: Workspace Context Restoration And Validation

Goal:

Restore and verify context-enabled workflows.

Must validate:

- git status
- git diff
- related files
- logs
- `context_hints`
- context truncation
- Codex safety behavior
- ChatGPT Web can see the expected context marker

Example validation file:

```text
bridge_test_context.txt
```

Priority: P1.

### P1: Pro Budget Routing Validation

Current strategy:

- simple / normal problems use GPT-5.5
- 30min-2h complex problems use `deep_lite`
- 2h+ strategic problems use `pro_deep`

Must validate:

- `config.yaml` profiles are present
- `AGENTS.md` rules are present
- Codex selects expected profiles semantically
- simple problems do not consume Pro
- true Pro-level problems can escalate to `pro_deep`

Priority: P1.

## Designed But Not Delivered

### route_to_web_lead

Goal:

Add one unified routing tool:

```text
route_to_web_lead
```

Inputs:

- `message`
- `intent`
- `force_profile`

Responsibilities:

- classify architecture / review / debug
- select `fast / balanced / deep_lite / pro_deep / review / pro_review / debug / pro_debug`
- call the corresponding MCP tool
- return the tool result

Priority: P2.

### Deep Thinking Watchdog

Goal:

Avoid confusing true deep thinking with a stuck Web page.

Future behavior:

- response start timeout
- response stall timeout
- max wall time
- deep thinking extension
- text growth detection
- stop button detection
- thinking indicator detection
- partial response handling

Current MVP only validates fast marker early return.

Priority: P2.

### Web Model UI Switching

Goal:

Reliably switch ChatGPT Web model/profile when appropriate.

Need to validate:

- model selector open
- GPT-5.5 selection
- Pro / Pro extension selection
- fallback when selection fails
- selected model logging

Priority: P2.

### Tab Maintenance Tools

Desired tools:

- `bridge_tab_health_check`
- `bridge_close_extra_tabs`

Desired validation:

```text
bridge_tab_health_check
bridge_close_extra_tabs dry_run=true keep_latest=1
bridge_close_extra_tabs dry_run=false keep_latest=1
```

Priority: P0/P1 because tab growth affects daily use.

## Deferred

### CDP Daemon

Long-term option:

```text
AI Chrome daemon
-> remote-debugging-port
-> Playwright connect_over_cdp
-> MCP connects to existing browser
```

Priority: P3.

### Automatic Triggers

Examples:

- compile fails 3 times -> call `debug_pro_error`
- large diff -> call `review_pro_code`
- architecture question -> call `ask_pro_architect`

Priority: P3.

### Long-Term Project Memory

Possible artifacts:

- `.bridge_memory.json`
- `architecture.md`
- `project_context.md`
- `coding_style.md`

Priority: P3.

### Productized Review / Debug Loops

Future improvements:

- diff truncation
- error log parsing
- multi-turn debug context
- review result converted into execution tasks
- Codex applies review-driven patches

Priority: P2/P3.

## Immediate Priority Queue

### P0. Fix And Validate Tab Leak

Acceptance:

```text
Repeated ask_pro_architect calls do not increase Chrome tab count.
```

### P0. Validate review_pro_code

Acceptance:

```text
review 当前 git diff
```

returns through ChatGPT Web.

### P0. Validate debug_pro_error

Acceptance:

```text
分析这个错误：Target page, context or browser has been closed
```

returns through ChatGPT Web.

### P1. Validate Natural Language Routing

Acceptance:

```text
这个模块架构怎么看？
```

automatically routes to:

```text
ask_pro_architect profile=balanced
```

### P1. Restore And Validate Workspace Context

Acceptance:

ChatGPT Web can see a known context marker from the workspace.

## One-Line Status

Delivered:

```text
MVP minimal Web Bridge: ask_pro_architect can truly call ChatGPT Web and return to Codex.
```

Not yet daily-use complete:

```text
tab cleanup, review/debug validation, natural language routing validation, model budget validation, and workspace context restoration.
```
