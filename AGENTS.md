# pro_bridge_codex Agent Rules

# Highest Project Rule

All natural-language Codex requests must interact with the Web GPT through MCP first
unless they are explicitly deterministic local operations.

This is the highest project-level workflow rule for `pro_bridge_codex`.

For any natural-language question, requirement, architecture discussion, code change,
debugging request, review request, test strategy, implementation plan, correction, or
decision request, Codex must first call:

`route_to_web_lead`

If `route_to_web_lead` is unavailable, Codex must call:

`ask_pro_architect`

Codex must not answer these requests directly before the Web GPT / Web Lead
returns a plan, clarification, review, or analysis.

The only exception is when the user explicitly starts the message with:

`本地执行：`

In that case, Codex may perform the requested local action without first calling
Web GPT.

## Routing Safety Guards

- Never route content that originated from a Web MCP return or is already marked as
  Web-reviewed; this prevents Web-to-Codex-to-Web recursion.
- A single user turn may make at most one automatic Web Lead call.
- Deterministic local operations such as explicit shell commands, file reads, Git status,
  builds, and tests may execute locally without a Web call.
- If Web MCP times out, is unavailable, or authentication fails, retry at most once, then
  continue locally with clearly stated assumptions instead of blocking or retrying forever.

# Web-First Mandatory Workflow

## Core Principle

Codex is the executor.

Web Lead is the planner, requirement analyst, architect, reviewer, and debugger.

Codex must not independently decide implementation strategy for natural language requests.

Codex must not independently answer project-related questions before routing them to Web GPT through MCP.

## Default Routing

For any user request written in natural language, Codex must first call:

`route_to_web_lead`

If `route_to_web_lead` is unavailable, Codex must call:

`ask_pro_architect`

## Local Execution Exception

Codex may execute directly only when the user explicitly starts the message with:

`本地执行：`

Examples:

- `本地执行：查看 git status`
- `本地执行：运行 pytest`
- `本地执行：打开 README.md`

Without this prefix, route to Web Lead first.

Do not answer project questions directly before `route_to_web_lead` or fallback
`ask_pro_architect` returns.

## Requirement Refinement

When the user request is vague, Codex must not ask the user to rewrite it.

Instead, send the vague request to Web Lead.

Web Lead should:

- infer intent
- list assumptions
- refine requirements
- produce implementation plan
- provide Codex execution steps

## Implementation Rule

Codex may implement only after receiving a Web Lead plan.

## User Correction Rule

If the user interrupts with a correction, reminder, or clarification during implementation, Codex must route the correction to Web Lead before continuing.

## Pro Budget Principle

Pro / Pro extension quota is limited and should be treated as scarce.

Default natural-language planning should use `profile=balanced`.

Use `profile=deep_lite` for multi-module plans, multi-provider Web AI design, or 30-minute to 2-hour engineering problems.

Use `profile=pro_deep` only when the user explicitly requests Pro, or when the problem is a 2h+ high-value architecture, patent, safety-critical, long-term roadmap, or repeated unresolved debugging problem.

## Examples

User:

`实现未完成需求`

Action:

Call `route_to_web_lead`.

Then execute returned plan.

User:

`这个模块架构怎么看？`

Action:

Call `route_to_web_lead`.

User:

`后续要接入豆包、DeepSeek、小米，多 Web AI 对比方案，给出设计`

Action:

Call `route_to_web_lead`.

User:

`不对，先修 tab 泄漏`

Action:

Call `route_to_web_lead` with correction context.

User:

`本地执行：查看 git diff`

Action:

Run git diff locally.
