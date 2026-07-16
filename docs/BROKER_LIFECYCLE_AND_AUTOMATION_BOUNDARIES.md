# Broker Lifecycle and Automation Parameter Boundaries

Status: proposed design for the v0.6.4 reliability work.

## Purpose

`web-bridge-codex` must treat the ChatGPT Web browser as a recoverable external
resource. A browser tab, persistent context, Broker process, Codex task, or
network connection can disappear independently. One failed resource must not
poison every project request, cause a duplicate prompt, or silently turn a
Web-First request into a locally planned request.

This document defines ownership boundaries before implementation.

## Goals

- One user-scoped Broker owns the dedicated AI Chrome profile.
- Each local project has an isolated persisted ChatGPT conversation mapping.
- Concurrent callers are serialized at the browser interaction boundary.
- A closed or crashed browser context is detected, discarded, and recovered.
- Automatic recovery never sends the same prompt twice.
- Automated callers can identify their origin without changing conversation
  semantics.
- Failures remain diagnosable through structured stages and request IDs.

## Non-goals

- Do not support controlling a user's normal Chrome profile.
- Do not run multiple simultaneous prompts in one ChatGPT conversation.
- Do not guarantee that an external ChatGPT Web service is always available.
- Do not treat a successful CI run as proof of a logged-in real-device call.

## Ownership Model

```text
Codex task
  -> MCP tool server
  -> BrowserBrokerClient
  -> one BrowserBrokerServer per user/profile
  -> one ChatGPTWebAdapter
  -> one persistent Playwright BrowserContext
  -> transient request page plus optional about:blank keepalive page

ProjectSessionRegistry
  project root hash -> canonical ChatGPT conversation URL
```

The Broker owns Chrome and Playwright lifecycle only. The project session
registry owns conversation URLs only. Neither component may infer ownership
from the other's in-memory state.

## Broker State Machine

The Broker exposes a single authoritative lifecycle state.

| State | Meaning | Accepted request behavior |
|---|---|---|
| `STOPPED` | No Playwright process or Context exists. | Start recovery and launch. |
| `STARTING` | Launch is in progress. | Queue request. |
| `READY` | Context is live and event handlers are installed. | Process one queued request. |
| `RECOVERING` | Context was closed, crashed, or invalidated. | Queue request; rebuild once. |
| `DEGRADED` | Recovery attempt failed. | Return structured, retryable pre-send error. |
| `STOPPING` | Explicit shutdown is in progress. | Reject new work as retryable. |

State transitions are protected by the Broker's lifecycle lock. A request may
observe a Context only after the Broker has entered `READY` for the current
context generation.

## Context Generation and Invalidations

Each successfully launched BrowserContext receives a monotonic
`context_generation` value. The Broker must install close and crash listeners
at launch time.

When a close or disconnect event occurs:

1. Mark the generation invalid under the lifecycle lock.
2. Clear the cached Context and Playwright references.
3. Move the Broker to `RECOVERING`.
4. Emit `browser.context.invalidated` with the generation and cause.
5. Never return that Context to a later request.

`context.pages` is diagnostic data only. An empty page list is not proof that a
Context is live. `BrowserContext.new_page()` failure with a closed-target error
is an invalidation signal, not an ordinary page error.

## Request State and Retry Rules

Each Broker request has a request ID and an immutable delivery state.

| Delivery state | Meaning | Automatic recovery allowed |
|---|---|---|
| `NOT_STARTED` | No Context operation has begun. | Yes. |
| `PAGE_OPENING` | Context exists but no prompt has been submitted. | Yes, once. |
| `PROMPT_NOT_SENT` | Page navigation or selectors failed before send. | Yes, once. |
| `PROMPT_SENT` | Web UI acknowledged the user turn. | No automatic resend. |
| `RESPONSE_OBSERVED` | Request-bound assistant turn exists. | Continue observer only. |
| `TERMINAL` | Request ended. | No retry. |

If `new_page()`, navigation, or a Context event fails while the request is in
`NOT_STARTED`, `PAGE_OPENING`, or `PROMPT_NOT_SENT`, the Broker must:

1. Invalidate the Context generation.
2. Launch one fresh Context.
3. Retry the request exactly once.
4. Include `recovery_attempt=1` and `web_prompt_sent=false` in logs.

If the prompt may have been sent, the Broker must not replay it. It returns a
structured result with `web_prompt_sent=unknown` or `true` and lets Codex or the
user decide whether to continue manually.

## Conversation Mode Is Not Request Origin

`conversation_mode` describes how a request relates to a project's ChatGPT
conversation. Its public values are only:

| Value | Meaning |
|---|---|
| `reuse_or_create` | Reuse the saved project conversation, otherwise create and save one. |
| `new` | Start a new project conversation and replace the saved mapping after success. |
| `one_shot` | Use a temporary conversation without changing the saved mapping. |

`automation` is not a conversation mode. It belongs in a separate optional
`request_origin` field with values such as `interactive`, `automation`, and
`scheduled`.

For backward compatibility, the MCP boundary may accept legacy
`conversation_mode=automation` for one release cycle, log
`conversation_mode_legacy_alias`, convert it to `reuse_or_create`, and attach
`request_origin=automation`. Unknown values must produce a schema-level error
before a Broker request is created; they must never reach the Adapter as an
unvalidated string.

## Concurrency Policy

One physical BrowserContext and one ChatGPT conversation cannot safely receive
two simultaneous UI submissions. The Broker uses a global FIFO browser queue.

- Same project: requests are additionally ordered by project key so prompts are
  appended in a deterministic conversation order.
- Different projects: requests remain distinct by project session mapping but
  still use the global browser queue.
- A queued request records queue wait duration and can be cancelled before its
  prompt is sent.
- A failed request must release both the project lock and global queue slot.

The product should describe this behavior as "concurrent submission with safe
serialized Web execution", not as simultaneous ChatGPT generation.

## Web-First Failure Contract

The MCP result must distinguish these cases:

- `web_unavailable_before_send`: safe to retry or ask the user to retry.
- `web_uncertain_after_send`: do not resend; inspect the project conversation.
- `web_response_complete`: safe to pass the response to Codex.
- `web_policy_blocked`: local execution requires an explicit user choice or the
  `本地执行：` prefix.

For normal natural-language requests, a Web failure must not be labeled
"Web Bridge used successfully". The UI and logs must show the actual terminal
state and whether a Web answer was received.

## Persistence and Privacy Boundaries

- `ProjectSessionRegistry` persists only canonical conversation URLs and a
  project-name hint. It needs interprocess locking or a single-writer Broker
  contract to prevent lost updates.
- Interaction memory must not persist full prompts and replies by default.
  Store bounded operational metadata only: request ID, timestamps, state,
  project key, response length, and terminal reason.
- Workspace context collection must use allowlisted paths, size limits, and
  secret redaction before transfer. Recursive log discovery is not an adequate
  privacy boundary.

## Observability Contract

Every request must emit these structured stages:

```text
broker.request.queued
broker.context.ready
broker.context.invalidated
broker.recovery.start
broker.recovery.done
web.prompt.send.start
web.prompt.send.acknowledged
web.response.complete
broker.request.terminal
```

Required fields are `request_id`, `project_key`, `context_generation`,
`request_origin`, `conversation_mode`, `web_prompt_sent`, terminal state, and
recovery attempt count. Prompt content, cookies, and local file contents must
not be logged by default.

## Migration Plan

1. Add the Broker lifecycle state and Context invalidation listener.
2. Add the `request_origin` parameter and typed conversation-mode validation.
3. Add one pre-send recovery retry.
4. Replace raw interaction-memory persistence with bounded operational records.
5. Add fault-injection tests before changing default behavior.
6. Release only after the matrix in
   `docs/BROKER_FAULT_INJECTION_TEST_MATRIX.md` passes.

