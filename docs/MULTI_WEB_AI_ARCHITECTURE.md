# Multi Web AI Architecture

## Goal

The long-term goal is to extend `web-bridge-codex` from a single ChatGPT Web bridge into a multi-Web-AI planning system.

Target workflow:

```text
User request in Codex
-> Web-First router
-> dispatch one prompt to multiple Web AI providers
-> collect independent answers
-> normalize answers
-> compare common points and conflicts
-> synthesize the most detailed implementation plan
-> Codex executes the final plan
-> Codex validates and reports result
```

Planned providers:

- ChatGPT Web
- Doubao Web
- DeepSeek Web
- Xiaomi Web AI
- other free/open Web AI providers

The system should prefer free/currently available Web AI capacity first. Pro or scarce premium capacity should be reserved for final arbitration, high-risk architecture decisions, or repeated disagreement.

## Core Principle

Codex is the executor.

Web AI providers are planners, reviewers, and alternative reasoners.

No Web AI provider should directly modify code. Only Codex applies the final synthesized plan.

## High-Level Architecture

```text
Codex
  |
  v
Web-First MCP Server
  |
  v
Task Orchestrator
  |
  v
Prompt Planner
  |
  v
Provider Router
  |-------------------|-------------------|-------------------|
  v                   v                   v                   v
ChatGPT Web       Doubao Web          DeepSeek Web        Xiaomi / Free Web
Adapter           Adapter             Adapter             Adapter
  |                   |                   |                   |
  v                   v                   v                   v
ProviderResponse  ProviderResponse    ProviderResponse    ProviderResponse
  |                   |                   |                   |
  |-------------------|-------------------|-------------------|
  v
Response Collector
  |
  v
Response Normalizer
  |
  v
Consensus Engine
  |
  v
Final Plan Synthesizer
  |
  v
Codex Execution Plan
  |
  v
Codex Executor
```

## Module Responsibilities

### 1. Task Orchestrator

The Task Orchestrator receives the user request from Codex and decides whether multi-provider routing is needed.

Responsibilities:

- classify task type
- estimate complexity
- decide whether one provider is enough
- decide whether multiple free providers should be used
- decide whether Pro/premium final arbitration is justified
- package the final task as `TaskSpec`

Example task types:

- `simple_question`
- `requirement_refinement`
- `architecture_design`
- `code_review_strategy`
- `debug_strategy`
- `large_refactor_plan`
- `execution_plan`

### 2. Prompt Planner

The Prompt Planner turns one user request into provider-specific prompts.

It should not always send the exact same prompt to every provider. Different providers can be asked for different perspectives.

Example:

```text
Doubao:
Focus on product shape, MVP path, user workflow, and Chinese requirement clarity.

DeepSeek:
Focus on engineering architecture, module boundaries, interfaces, and failure modes.

Xiaomi / Free Web AI:
Focus on maintainability, rollout risk, and alternative low-cost designs.

ChatGPT Web:
Focus on synthesis, trade-offs, and final Codex execution plan.
```

### 3. Provider Router

The Provider Router selects which providers to call.

Rules:

- simple task: use current Web Lead only
- normal architecture: use ChatGPT Web or DeepSeek Web
- multi-module design: use Doubao + DeepSeek + ChatGPT Web
- disputed plan: ask one more free provider before using Pro
- final high-risk arbitration: use Pro only if needed

Provider calls should be concurrent where safe.

### 4. Provider Adapter

Each Web AI provider must implement the same interface.

Conceptual interface:

```python
class WebAIProvider:
    provider_id: str
    provider_name: str
    capability_tags: list[str]

    async def health_check(self) -> ProviderHealth: ...
    async def query(self, request: ProviderRequest) -> ProviderResponse: ...
    async def close_extra_tabs(self, dry_run: bool = True) -> TabCleanupResult: ...
```

Provider-specific details must stay inside the adapter:

- login state
- browser profile path
- input selector
- send selector
- response selector
- response completion detection
- tab cleanup
- popup handling
- retry policy

The core workflow must not know whether a provider uses `textarea`, `contenteditable`, Chinese button text, or a special response DOM.

### 5. Browser Runtime

The Browser Runtime provides shared browser automation primitives.

Suggested modules:

```text
browser/
  browser_runtime.py
  browser_profile_manager.py
  page_lifecycle.py
  selector_resolver.py
  response_extractor.py
  tab_cleaner.py
  screenshot_logger.py
```

Required behavior:

- one dedicated profile per provider
- fresh page per query
- cleanup before and after query
- no accumulation of provider tabs
- close only provider-owned tabs
- preserve non-provider user tabs
- collect screenshots/logs on failure

### 6. Response Collector

The Response Collector waits for provider responses and records failures without failing the whole workflow.

Rules:

- if one provider fails, continue with successful providers
- if all providers fail, return a clear failure
- if fewer than the minimum required providers return, mark result as degraded
- preserve raw answers for traceability

### 7. Response Normalizer

Different providers return different writing styles. The normalizer converts answers into a shared shape.

Suggested normalized schema:

```yaml
provider_id:
raw_answer:
summary:
recommended_architecture:
modules:
interfaces:
implementation_steps:
risks:
validation_plan:
open_questions:
confidence:
```

### 8. Consensus Engine

The Consensus Engine compares normalized answers.

It should identify:

- common points
- conflicting points
- missing but important risks
- provider-specific unique ideas
- likely best implementation direction

First MVP can use rule-based comparison:

- common module names
- repeated risk categories
- repeated implementation steps
- same recommended execution order

Later versions can add embeddings or LLM-based structured comparison.

### 9. Final Plan Synthesizer

The synthesizer produces one final plan for Codex.

It should not simply concatenate all answers.

Output format:

```markdown
# Final Codex Execution Plan

## Interpreted Goal

## Consensus Summary

## Disagreements And Decisions

## Final Architecture

## Implementation Steps

## Files Likely To Change

## Validation Plan

## Rollback Plan

## Risks

## Codex Execution Instructions
```

The plan must be detailed enough that Codex can execute without inventing architecture.

### 10. Codex Executor Gateway

The gateway converts the final synthesized plan into Codex-safe execution.

It should include:

- allowed files
- forbidden files
- implementation steps
- validation commands
- log files to inspect if failure occurs
- when to ask Web Lead again

Codex should not execute raw provider answers. It should execute only the final synthesized plan.

## Core Data Structures

### TaskSpec

```yaml
task_id:
user_message:
task_type:
complexity:
requires_multi_provider:
requires_workspace_context:
requires_code_execution:
preferred_providers:
forbidden_actions:
acceptance_criteria:
```

### ProviderRequest

```yaml
task_id:
provider_id:
prompt:
system_role:
expected_output_format:
timeout_seconds:
max_retries:
context_policy:
```

### ProviderResponse

```yaml
task_id:
provider_id:
success:
raw_answer:
normalized_answer:
elapsed_seconds:
error:
screenshot_path:
model_label:
```

### ConsensusResult

```yaml
task_id:
successful_providers:
failed_providers:
common_points:
conflicting_points:
unique_ideas:
missing_risks:
confidence_score:
requires_more_review:
recommended_final_direction:
```

### CodexExecutionPlan

```yaml
objective:
files_to_inspect:
files_allowed_to_modify:
files_forbidden_to_modify:
implementation_steps:
validation_commands:
acceptance_criteria:
rollback_strategy:
when_to_route_back_to_web_lead:
```

## Routing Policy

### Default

Use Web-First routing for natural-language requests.

### Free-first

Use free/current Web AI providers before premium Pro capacity.

### Consensus threshold

Initial recommendation:

```yaml
consensus:
  min_successful_answers: 2
  majority_required: true
  allow_degraded_single_provider: true
  require_user_confirmation_on_conflict: true
```

### Provider selection examples

| Task | Providers |
|---|---|
| simple clarification | ChatGPT Web |
| Chinese requirement refinement | Doubao + ChatGPT Web |
| engineering architecture | DeepSeek + ChatGPT Web |
| multi-provider roadmap | Doubao + DeepSeek + ChatGPT Web |
| high-risk final decision | free providers first, Pro final if needed |

## Configuration Sketch

```yaml
multi_web_ai:
  enabled: false
  default_mode: consensus
  min_successful_answers: 2
  free_first: true
  pro_as_final_arbitrator: true

providers:
  chatgpt:
    enabled: true
    adapter: chatgpt_web
    base_url: "https://chatgpt.com"
    user_data_dir: "C:/Users/15314/web_ai_profiles/chatgpt"
    capability_tags:
      - architecture
      - synthesis
      - final_plan

  doubao:
    enabled: false
    adapter: doubao_web
    base_url: "https://www.doubao.com"
    user_data_dir: "C:/Users/15314/web_ai_profiles/doubao"
    capability_tags:
      - chinese_requirements
      - product
      - mvp

  deepseek:
    enabled: false
    adapter: deepseek_web
    base_url: "https://chat.deepseek.com"
    user_data_dir: "C:/Users/15314/web_ai_profiles/deepseek"
    capability_tags:
      - engineering
      - code
      - algorithms

  xiaomi:
    enabled: false
    adapter: xiaomi_web
    base_url: ""
    user_data_dir: "C:/Users/15314/web_ai_profiles/xiaomi"
    capability_tags:
      - alternative_review
      - risk
```

## Proposed Directory Structure

```text
core/
  task_orchestrator.py
  prompt_planner.py
  provider_router.py
  response_collector.py
  response_normalizer.py
  consensus_engine.py
  final_plan_synthesizer.py
  codex_execution_gateway.py

adapters/
  web_ai_base.py
  chatgpt_web.py
  doubao_web.py
  deepseek_web.py
  xiaomi_web.py
  generic_web.py

browser/
  browser_runtime.py
  browser_profile_manager.py
  page_lifecycle.py
  tab_cleaner.py
  selector_resolver.py
  response_extractor.py
  screenshot_logger.py

docs/
  MULTI_WEB_AI_ARCHITECTURE.md
```

## MVP Rollout Plan

### Phase 0: Stabilize current ChatGPT Web bridge

Status: in progress.

Required:

- no tab leak
- stable `route_to_web_lead`
- stable `ask_pro_architect`
- clear logs and diagnostics

### Phase 1: Introduce internal abstractions only

Add:

- `WebAIProvider`
- `ProviderRequest`
- `ProviderResponse`
- `ConsensusResult`
- `CodexExecutionPlan`

Only ChatGPT Web is active.

### Phase 2: Add multi-provider orchestration with mock provider

Add:

- provider registry
- response collector
- normalizer
- consensus engine
- final plan synthesizer

Use a local fake provider first to validate orchestration without browser instability.

### Phase 3: Add DeepSeek Web provider

DeepSeek is the recommended first external provider after ChatGPT because it is useful for engineering/code reasoning.

Acceptance:

- one prompt can be sent to ChatGPT + DeepSeek
- both responses are collected
- consensus summary is generated
- Codex receives one final plan

### Phase 4: Add Doubao Web provider

Doubao is useful for Chinese requirement interpretation, product/MVP framing, and user-facing design.

### Phase 5: Add Xiaomi / generic free Web provider

Add provider-specific selectors and fallback extraction.

### Phase 6: Enable final arbitration policy

Only after free providers return:

- if they agree, synthesize directly
- if they disagree, ask ChatGPT Web or Pro for final arbitration
- if Pro quota is scarce, ask user before Pro final review

## Acceptance Criteria

The goal is achieved when:

- a single Codex request can route to multiple Web AI providers
- at least two provider responses can be collected
- failed providers do not crash the workflow
- common points and conflicts are identified
- one final detailed execution plan is returned
- Codex executes only the synthesized plan
- tab cleanup prevents browser growth across repeated calls

## Non-goals For Current MVP

- do not connect all providers at once
- do not let providers edit code
- do not call Pro for every request
- do not depend on one provider being always available
- do not build complex ML consensus before rule-based consensus works

## Key Risks

- Web UI selectors change often
- login state can expire
- free providers can rate-limit or show captchas
- multiple providers can agree and still be wrong
- browser tab leaks can make all providers unstable
- sending workspace context to multiple external websites increases privacy risk

## Recommended Next Step

Implement internal data structures and orchestration with only ChatGPT Web active.

This keeps the current MVP stable while preparing the architecture for Doubao, DeepSeek, Xiaomi, and other free Web AI providers.


