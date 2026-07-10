# Web-First Execution Workflow

## Highest Project Rule

All project-related Codex Q&A must interact with Web GPT through MCP first.

For any project-related question, requirement, architecture discussion, code
change, debugging request, review request, validation strategy, or user
correction, Codex must call:

```text
route_to_web_lead
```

If unavailable, Codex must call:

```text
ask_pro_architect
```

Codex must not answer project questions directly before Web GPT returns a plan,
analysis, review, or clarification.

The only direct-local exception is the explicit prefix:

```text
本地执行：
```

## Purpose

`pro_bridge_codex` is a Web-First Codex workflow.

Codex is the local executor. Web Lead is the planner.

The default flow is:

```text
User vague request
-> Codex routes request to Web Lead through MCP
-> Web Lead refines requirement
-> Web Lead produces execution plan
-> Codex implements the plan
-> Codex runs validation
-> If issue occurs, Codex routes issue back to Web Lead
-> Codex applies revised plan
```

## Role Split

Codex handles:

- file edits
- command execution
- patch application
- build and validation
- reporting diffs, logs, and test results

Web Lead handles:

- requirement interpretation
- assumptions and non-goals
- architecture decisions
- implementation plan
- validation strategy
- review and debug strategy

## Default Routing

All natural-language requests should first call:

```text
route_to_web_lead
```

If that tool is unavailable, use:

```text
ask_pro_architect
```

## Local Execution Exception

Codex may execute directly only when the user starts the request with:

```text
本地执行：
```

Examples:

```text
本地执行：查看 git diff
本地执行：运行 pytest
本地执行：打开 README.md
```

## Vague Requirement Handling

When the user says something vague, such as:

```text
实现未完成需求
```

Codex should not guess and implement directly.

Codex should route the message to Web Lead. Web Lead should return:

- interpreted goal
- assumptions
- non-goals
- required implementation
- likely files to change
- step-by-step execution plan
- validation plan
- risks
- Codex execution instructions

## User Correction Flow

If the user corrects direction during execution, route that correction back to Web Lead.

Examples:

```text
不对，先修 tab 泄漏
不要改模型策略，只修 browser 生命周期
这个不是我要的，重新理解需求
```

Codex should include:

- original plan summary
- current execution status
- user correction
- current diff summary
- relevant logs or failure stage

## Profile Selection

Use `balanced` by default.

Use `fast` only for simple confirmation or explicitly fast requests.

Use `deep_lite` for multi-module planning, multi-Web-AI design, or complex-but-not-Pro work.

Use `pro_deep` only for explicit Pro requests or high-value 2h+ problems, such as patent strategy, safety-critical architecture, long-term roadmap decisions, or repeated unresolved root-cause analysis.

## Expected Web Lead Output

```markdown
# Web Lead Plan

## Interpreted Goal

## Assumptions

## Scope

## Non-goals

## Recommended Plan

## Step-by-step Codex Execution

## Files Likely To Change

## Validation Plan

## Risks

## When To Ask Web Lead Again
```

## Execution Feedback Format

Before executing a Web Lead plan, Codex should report:

```text
[WEB_LEAD_PLAN_RECEIVED]
profile=<profile>
tool=<tool>
summary=<one-line-summary>

[CODEX_EXECUTION_START]
```

If execution is blocked:

```text
[CODEX_BLOCKED]
reason=<error>
next_action=route_back_to_web_lead
```

Then Codex should call `route_to_web_lead` again with the correction or failure context.
