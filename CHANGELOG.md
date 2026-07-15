# Changelog

## 0.6.1

- Move persistent Playwright/Chrome ownership into one user-scoped Browser Broker shared by every Codex MCP process.
- Serialize cross-project Web requests through one authenticated loopback queue while preserving project conversation mappings in the broker process.
- Add fail-fast, truthful delivery states so transport loss never claims a Web prompt was sent when it was not.
- Recover stale broker state after crashes, exit after an idle timeout, and gracefully release the broker before release upgrades.
- Add a packaged two-process broker self-test to Windows, Linux, Intel macOS, and Apple Silicon macOS release CI.

## 0.6.0

- Introduce the singleton Browser Broker protocol and global request queue.

## 0.5.1

- Report cross-process Chrome profile ownership conflicts before prompt delivery.

## 0.5.0

- Keep one dedicated ChatGPT Web browser context alive inside the MCP process after its first successful launch.
- Open and close only the request tab for each Web call while preserving a single `about:blank` keepalive tab.
- Serialize requests that share one AI Chrome profile, preventing cross-project tab and response races.
- Add `bridge_browser_status` and `bridge_browser_shutdown` for worker diagnostics and controlled profile release.
- Extend release MCP-tool verification for the new browser-worker tools.

## 0.4.0

- Reuse one ChatGPT Web conversation per local project by default.
- Persist only a hashed project key and canonical conversation URL in an atomically written local registry.
- Add `conversation_mode` controls: `reuse_or_create`, `new`, and `one_shot`.
- Recover once only when a saved conversation is definitively unavailable; transient Web failures retain the mapping.
- Add deterministic tests for project isolation, safe persistence, and adapter reuse routing.

## 0.2.0-dev

- Add the Windows user-level installer, repair, diagnostics, and uninstaller.
- Add a bootstrap script for installing from the public GitHub repository.
- Register `web-bridge-codex` as a Codex MCP server without replacing existing MCP entries.
- Install a managed global Web-First workflow rule and a dedicated local Chrome profile.

## 0.1.0

- Delivered the MVP ChatGPT Web bridge for `ask_web_architect`.
