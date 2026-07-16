# Broker Fault-Injection Test Matrix

Status: proposed v0.6.4 release gate.

## Test Rules

- Every recovery test records whether the Web prompt was sent.
- A request may be retried automatically only while `web_prompt_sent=false`.
- Tests that manipulate Chrome use the dedicated AI Profile only.
- Packaged-release tests run against the installed artifact, not the source
  checkout.
- A CI pass and a real logged-in browser pass are separate evidence classes.

## Automated Unit Tests

| ID | Injection | Expected result | Evidence |
|---|---|---|---|
| U-01 | Pass `reuse_or_create`, `new`, and `one_shot`. | Each reaches normalized Adapter input unchanged. | Parameterized schema test. |
| U-02 | Pass legacy `conversation_mode=automation`. | Normalizes to `reuse_or_create`; `request_origin=automation`; warning logged. | MCP boundary unit test. |
| U-03 | Pass an unknown conversation mode. | Schema or boundary failure before Broker enqueue. | No Adapter call assertion. |
| U-04 | Context close event fires. | Cached Context and Playwright handles are invalidated; Broker enters `RECOVERING`. | Lifecycle state assertion. |
| U-05 | Cached Context returns `pages=[]` but `new_page()` raises TargetClosed. | Context is invalidated; one fresh launch is attempted. | Recovery count equals one. |
| U-06 | Fresh recovery launch succeeds before send. | Original request completes; one prompt submission only. | Prompt-send spy count equals one. |
| U-07 | Fresh recovery launch fails. | Structured `web_unavailable_before_send`; no leaked lock or queue slot. | Broker state becomes `DEGRADED`. |
| U-08 | Failure occurs after send acknowledgement. | No automatic replay. | Prompt-send spy count remains one. |
| U-09 | Same-project concurrent calls. | FIFO prompt order; each request gets its own response marker. | Ordered call log. |
| U-10 | Different-project concurrent calls. | Global queue serializes browser work; conversation URL mapping remains isolated. | Two project-key assertions. |
| U-11 | Queued request is cancelled before send. | Removed from queue; no page or prompt is created. | `web_prompt_sent=false`. |
| U-12 | Context closes during response observation. | Return `web_uncertain_after_send`; do not resend. | Terminal state and marker absence. |
| U-13 | Session registry receives concurrent writes. | No lost project mapping and valid JSON remains. | Multiprocess or file-lock test. |
| U-14 | Interaction memory receives malformed or concurrent input. | No crash, no corrupt JSON, bounded metadata only. | File-content assertion. |
| U-15 | Context bundle contains token-like text in a log. | Secret is redacted or excluded before prompt construction. | Prompt snapshot assertion. |

## Broker Integration Tests

| ID | Setup and injection | Expected result | Environment |
|---|---|---|---|
| I-01 | Start Broker, force Context close, send a new request. | Broker launches a new Context and succeeds before send. | Playwright fake/context harness. |
| I-02 | Start Broker, close dedicated Chrome externally, then request. | No stale Context reuse; one automatic pre-send recovery. | Windows real Chrome smoke. |
| I-03 | Stop Broker process while an MCP client is idle, then send a request. | Client discovers stale state and starts a replacement Broker. | Windows packaged artifact. |
| I-04 | Kill Chrome while response is generating. | No duplicate prompt; explicit uncertain-after-send result. | Windows real Chrome smoke. |
| I-05 | Leave stale profile lock without live Chrome process. | Launch proceeds or safely removes lock only when configured. | Windows and Linux. |
| I-06 | Leave a live dedicated-profile Chrome process. | Clear profile-owner error with matching process information. | Windows real Chrome smoke. |
| I-07 | Submit two projects concurrently. | Both finish with distinct markers and no conversation contamination. | Windows real Chrome smoke. |
| I-08 | Submit two requests to one project concurrently. | Web pages receive prompts in FIFO order in one conversation. | Windows real Chrome smoke. |

## Package and Installation Tests

| ID | Injection | Expected result | Platform |
|---|---|---|---|
| P-01 | Fresh install with custom `CODEX_HOME`. | Canonical MCP entry and Web-First rules are added once. | Windows, Linux, macOS. |
| P-02 | Upgrade while Codex/MCP runtime still holds a file. | Installer stops before replacement and gives the exact restart action. | Windows. |
| P-03 | Upgrade after process exit. | Runtime replacement is atomic; profile and unrelated Codex configuration are preserved. | Windows. |
| P-04 | Interrupted application copy or archive extraction. | Previous runnable installation remains intact or repair can restore it. | Windows, Linux, macOS. |
| P-05 | Legacy MCP table and managed rule exist. | Migration produces exactly one canonical registration and one managed rule. | Windows, Linux, macOS. |
| P-06 | Chrome absent. | Installer offers only approved install guidance; no partial MCP registration. | Windows, Linux, macOS. |
| P-07 | Installed native artifact starts `tools/list`. | All canonical tool names and typed parameters are present. | Windows, Linux, macOS. |

## Real Device Acceptance

These tests require a dedicated profile logged in to ChatGPT. They are not
replaced by CI.

| ID | Action | Acceptance condition |
|---|---|---|
| R-01 | Fresh Codex task after install or upgrade. | `bridge_health_check`, `route_to_web_lead`, and `ask_web_architect` are callable. |
| R-02 | Ask for a unique marker. | Marker is visible in ChatGPT and returned to Codex. |
| R-03 | Ask a long-running deep question. | No premature timeout while generation is visibly active. |
| R-04 | Close AI Chrome during an idle Broker, then ask a marker question. | Browser recovers automatically and returns the marker once. |
| R-05 | Close AI Chrome during an active answer. | No duplicate ChatGPT user turn; Codex receives an explicit uncertain-after-send result. |
| R-06 | Launch two projects concurrently. | Each project uses its own persisted conversation URL and receives its own marker. |
| R-07 | Launch two calls for one project concurrently. | Both append in deterministic order to the same conversation. |
| R-08 | Restart Codex, then create a new task. | Tools load and first Web request recreates required Broker state. |

## Release Gate

A release candidate is blocked when any of the following is true:

- Any U, I, or P test marked required fails.
- R-02, R-04, R-05, R-06, or R-07 lacks current-release evidence on Windows.
- The runtime emits a stale-context reuse without a recovery attempt.
- A recovery path can submit a duplicate prompt.
- A natural-language request is reported as Web-reviewed without a completed
  Web response.
- Tag publication can be triggered by more than one workflow for the same
  artifact family.

## Evidence Required Per Release

- CI run URLs and artifact hashes.
- Automated test report with test IDs and platform.
- Sanitized real-device transcript for R-02 through R-07.
- Browser log excerpts containing request IDs, Context generation, recovery
  attempts, and `web_prompt_sent` state.
- A rollback artifact and documented uninstall/repair path.

