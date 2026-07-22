# Release process and acceptance gate

A green CI run alone is not permission to publish a stable release. A stable
release must pass every applicable gate below. If any gate is missing, failed,
or only assumed, publish a prerelease or stop the release.

## 1. Source and configuration gate

1. Update `VERSION` and the release notes.
2. Run the full unit suite. It must pass with no unexplained skip or xfail.
3. Confirm existing managed configurations migrate to the new policy without
   changing the dedicated Chrome Profile, unrelated Codex MCP entries, or
   user-owned settings.
4. Confirm the repository contains no Chrome Profile, log, cookie, token,
   virtual environment, or local configuration file.

## 2. Capability gate for ChatGPT Web

The bridge must not treat a successful click as a successful capability change.
It must read back the actual Web UI state before it sends a prompt.

| Request type | Required verified capability | Permitted fallback | Blocking failure |
|---|---|---|---|
| Ordinary question | `very_high` (`极高`) | None | Current capability cannot be read or `极高` cannot be read back. |
| Architecture, plan, or task design | `pro` (`Pro`) | Explicit, verified `very_high` only | `Pro` and its allowed fallback cannot be read back. |

For both paths, a failed capability check must return a structured error with
`web_prompt_sent=False`. It must not send the user prompt at a lower or unknown
capability.

## 3. Real-Web gate

Run these checks with the real dedicated Chrome Profile and an authenticated
ChatGPT Web session. Mock adapters, API fallback, unit tests, and browser smoke
tests do not replace this gate.

1. Start from a known lower capability such as `中` when practical.
2. Send one ordinary marker request through the production request path.
3. Verify logs show: current capability read, `very_high` selected, `very_high`
   read back, exactly one prompt send, and the marker returned to Codex.
4. Send one planning marker request through the production request path.
5. Verify logs show: current capability read, `pro` selected, `pro` read back,
   exactly one prompt send, and the marker returned to Codex.
6. Exercise a negative path by making capability confirmation unavailable in a
   controlled test; verify `web_prompt_sent=False` and that a later request can
   still recover.

If the account has no Pro capability, the planning path may pass only when the
logs explicitly show the verified `very_high` fallback. Silent fallback is not
acceptable.

## 4. Package and installation gate

1. `Validate delivery files` must pass on `main`.
2. Native package jobs must pass for Windows x64, Linux x64, macOS x64, and
   macOS arm64.
3. The generated package must contain the compiled runtime and no source-tree
   dependency.
4. On a clean or previously installed Windows device, completely exit Codex,
   run the release installer, restart Codex, verify `bridge_health_check`, and
   repeat at least the ordinary real-Web marker call.

## 5. Publish decision

Only after gates 1 through 4 pass:

1. Create and push an annotated tag, for example `v0.6.12`.
2. Wait for the release workflow to publish all platform archives and
   `SHA256SUMS.txt`.
3. Confirm the GitHub Release is neither draft nor prerelease.
4. Include known limitations, upgrade instructions, rollback instructions, and
   the required post-install verification in the release notes.

If a post-release installed-runtime test fails, mark the release as prerelease
or superseded and open a tracked issue. Do not describe it as a stable release.
